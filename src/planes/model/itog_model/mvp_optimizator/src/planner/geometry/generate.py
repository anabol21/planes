"""Генерация полос: область + препятствия + камера + GSD + угол."""

from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.models import Area, Obstacle, Swath, SurveyType, Point
from planner.utils.geo import make_local_transformer


def _camera_params_from_catalog(camera: dict[str, Any]) -> dict[str, float]:
    """Извлекает sensor_w_mm, sensor_h_mm, res_w_px, res_h_px, focal_mm."""
    specs = camera.get("specs", {})
    general = specs.get("general", {})
    perf = specs.get("performance", {})

    # Разрешение: "6000 x 4000 (24.3 MP)"
    res_raw = general.get("max_resolution") or general.get("resolution") or "6000x4000"
    res_w, res_h = 6000, 4000
    for token in str(res_raw).replace("x", " ").split():
        if token.replace(".", "").isdigit():
            continue
        if "×" in token:
            parts = token.split("×")
            if len(parts) == 2:
                try:
                    res_w = int(parts[0])
                    res_h = int(parts[1])
                except ValueError:
                    pass
            break
    # Альтернатива: "6000 x 4000"
    if "x" in str(res_raw).lower():
        parts = str(res_raw).lower().split("x")
        try:
            res_w = int(parts[0].strip())
            res_h = int(parts[1].strip().split()[0])
        except (ValueError, IndexError):
            pass

    # Матрица: "APS-C (23.5 x 15.6 mm)" или "23.5×15.6"
    sensor_raw = general.get("sensor_size") or general.get("sensor") or "23.5x15.6"
    sensor_w_mm, sensor_h_mm = 23.5, 15.6
    for sep in ("×", "x"):
        if sep in str(sensor_raw):
            parts = str(sensor_raw).split(sep)
            nums = [p.strip() for p in parts]
            try:
                sensor_w_mm = float(nums[0].split()[-1])
                sensor_h_mm = float(nums[1].split()[0])
                break
            except (ValueError, IndexError):
                continue

    focal_mm = float(perf.get("focal_length", 20.0).split()[0]) if "focal_length" in perf else 20.0

    return {
        "sensor_w_mm": sensor_w_mm,
        "sensor_h_mm": sensor_h_mm,
        "res_w_px": res_w,
        "res_h_px": res_h,
        "focal_mm": focal_mm,
    }


def compute_flight_and_swath(
    gsd_cm_per_px: float,
    camera_params: dict[str, float],
    overlap: float = 0.3,
) -> dict[str, float]:
    """
    Возвращает:
      h_agl_m — высота над рельефом,
      swath_width_m — ширина полосы на земле,
      spacing_m — шаг между полосами с учётом перекрытия.
    """
    gsd_m_per_px = gsd_cm_per_px / 100.0
    pixel_size_mm = camera_params["sensor_w_mm"] / camera_params["res_w_px"]

    h_agl_m = gsd_m_per_px * camera_params["focal_mm"] / pixel_size_mm
    swath_width_m = gsd_m_per_px * camera_params["res_w_px"]
    spacing_m = swath_width_m * (1.0 - overlap)

    return {
        "h_agl_m": h_agl_m,
        "swath_width_m": swath_width_m,
        "spacing_m": spacing_m,
    }


def generate_swaths_for_area(
    area: Area,
    obstacles: list[Obstacle],
    angle_deg: float,
    gsd_cm_per_px: float,
    camera: dict[str, Any],
    decomposition: str = "trapezoid",
    overlap: float = 0.3,
) -> tuple[list[Swath], float]:
    """
    Возвращает (swaths, h_agl_m).
    """
    cam = _camera_params_from_catalog(camera)
    geom_calc = compute_flight_and_swath(gsd_cm_per_px, cam, overlap)
    h_agl_m = geom_calc["h_agl_m"]
    spacing_m = geom_calc["spacing_m"]

    # Центр для локальной проекции
    poly_wgs = shape(area.polygon)
    c = poly_wgs.centroid
    fwd, inv = make_local_transformer(c.x, c.y)

    # Область в метрах
    poly_m = shape(area.polygon)
    poly_m = Polygon(
        [fwd.transform(x, y) for x, y in poly_m.exterior.coords],
        holes=[
            [fwd.transform(x, y) for x, y in interior.coords]
            for interior in poly_m.interiors
        ],
    )

    # Препятствия
    for obs in obstacles:
        obs_poly = shape(obs.polygon)
        obs_m = Polygon([fwd.transform(x, y) for x, y in obs_poly.exterior.coords])
        poly_m = poly_m.difference(obs_m)

    # Декомпозиция
    if decomposition == "triangulation":
        pieces = triangulation_decomposition(poly_m)
    else:
        pieces = trapezoid_decomposition(poly_m)

    # Полосы внутри каждого куска
    swaths: list[Swath] = []
    sid = 0
    for piece in pieces:
        for line in swaths_in_piece(piece, angle_deg=angle_deg, spacing_m=spacing_m):
            coords = list(line.coords)
            if len(coords) < 2:
                continue
            start = coords[0]
            end = coords[-1]
            lon_s, lat_s = inv.transform(start[0], start[1])
            lon_e, lat_e = inv.transform(end[0], end[1])
            length_m = float(line.length)
            if length_m < 5.0:
                continue
            swaths.append(
                Swath(
                    id=f"{area.id}-s{sid}",
                    area_id=area.id,
                    start=Point(lat=lat_s, lon=lon_s),
                    end=Point(lat=lat_e, lon=lon_e),
                    length_m=length_m,
                    segment_id=None,
                )
            )
            sid += 1

    return swaths, h_agl_m