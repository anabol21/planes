"""Генерация полос: область + препятствия + камера + GSD + угол + DEM."""

from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon, shape

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.io.dem import DEM, compute_h_asl
from planner.models import Area, Obstacle, Point, Swath
from planner.utils.geo import make_local_transformer


def _camera_params_from_catalog(camera: dict[str, Any]) -> dict[str, float]:
    specs = camera.get("specs", {})
    general = specs.get("general", {})
    perf = specs.get("performance", {})

    res_raw = general.get("max_resolution") or general.get("resolution") or "6000x4000"
    res_w, res_h = 6000, 4000
    if "x" in str(res_raw).lower():
        parts = str(res_raw).lower().split("x")
        try:
            res_w = int(parts[0].strip())
            res_h = int(parts[1].strip().split()[0])
        except (ValueError, IndexError):
            pass

    sensor_raw = general.get("sensor_size") or general.get("sensor") or "23.5x15.6"
    sensor_w_mm, sensor_h_mm = 23.5, 15.6
    for sep in ("×", "x"):
        if sep in str(sensor_raw):
            parts = str(sensor_raw).split(sep)
            try:
                sensor_w_mm = float(parts[0].strip().split()[-1])
                sensor_h_mm = float(parts[1].strip().split()[0])
                break
            except (ValueError, IndexError):
                continue

    focal_raw = perf.get("focal_length", "20")
    focal_mm = 20.0
    if focal_raw:
        try:
            focal_mm = float(str(focal_raw).split()[0])
        except (ValueError, IndexError):
            pass

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
    dem: DEM | None = None,
) -> tuple[list[Swath], float]:
    """
    Возвращает (swaths, h_agl_target).
    Каждая полоса получает h_agl_m и h_asl_m из DEM.
    """
    cam = _camera_params_from_catalog(camera)
    geom_calc = compute_flight_and_swath(gsd_cm_per_px, cam, overlap)
    h_agl_target = geom_calc["h_agl_m"]
    spacing_m = geom_calc["spacing_m"]

    poly_wgs = shape(area.polygon)
    c = poly_wgs.centroid
    fwd, inv = make_local_transformer(c.x, c.y)

    poly_m = Polygon(
        [fwd.transform(x, y) for x, y in poly_wgs.exterior.coords],
        holes=[
            [fwd.transform(x, y) for x, y in interior.coords]
            for interior in poly_wgs.interiors
        ],
    )

    for obs in obstacles:
        obs_poly = shape(obs.polygon)
        obs_m = Polygon([fwd.transform(x, y) for x, y in obs_poly.exterior.coords])
        poly_m = poly_m.difference(obs_m)

    if decomposition == "triangulation":
        pieces = triangulation_decomposition(poly_m)
    else:
        pieces = trapezoid_decomposition(poly_m)

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

            # DEM: берём высоту по центру полосы
            clat = (lat_s + lat_e) / 2.0
            clon = (lon_s + lon_e) / 2.0
            h_agl, h_asl = compute_h_asl(clat, clon, h_agl_target, dem)

            swaths.append(
                Swath(
                    id=f"{area.id}-s{sid}",
                    area_id=area.id,
                    start=Point(lat=lat_s, lon=lon_s, alt_m=h_asl),
                    end=Point(lat=lat_e, lon=lon_e, alt_m=h_asl),
                    length_m=length_m,
                    segment_id=None,
                    h_agl_m=h_agl,
                    h_asl_m=h_asl,
                )
            )
            sid += 1

    return swaths, h_agl_target