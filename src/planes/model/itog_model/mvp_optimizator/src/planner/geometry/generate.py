"""Генерация полос с разбиением, boustrophedon, продольным перекрытием
и горизонтальным буфером вокруг препятствий и запретных зон.

Декомпозиция работает вдоль направления полос:
перед декомпозицией полигон поворачивается на -angle,
полосы генерируются при angle=0, потом поворачиваются обратно.

ИСКЛЮЧЕНИЕ — fields2cover: F2C сам оптимизирует направление полос,
поэтому ему передаётся НЕповёрнутый полигон, и обратный поворот не
применяется. Угол angle_deg для F2C игнорируется.

Запретные зоны (NoFlyZone) вычитаются из полигона ВСЕГДА —
летать над ними нельзя, независимо от высоты. Препятствия
(Obstacle) вычитаются с буфером obstacle_buffer_m.

Методы декомпозиции:
  - trapezoid      — вертикальные резы через вершины;
  - triangulation  — Delaunay + merge выпуклых;
  - fields2cover   — Boustrophedon из C++ библиотеки F2C (опционально);
  - auto           — F2C если доступен, иначе trapezoid.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, shape

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.io.dem import BaseDEM
from planner.models import (
    Area,
    NoFlyZone,
    Obstacle,
    Point,
    Swath,
    SwathSegment,
)
from planner.utils.geo import make_local_transformer
from planner.utils.logging import log_warn


SEGMENT_LEN_M = 30.0
MIN_SWATH_LEN_M = 5.0
ENTRY_EXIT_AVG_N = 3

MAX_PENALTY_FACTOR = 5.0

G = 9.81


_INCH_SENSOR_MM: dict[str, tuple[float, float]] = {
    "1/1.7": (7.60, 5.70),
    "1/2.3": (6.17, 4.55),
    "1/2.5": (5.76, 4.29),
    "1/2.8": (5.27, 3.95),
    "1/3":   (4.80, 3.60),
    "1/4":   (3.60, 2.70),
}


# ============================================================
# Камера / GSD
# ============================================================

def _parse_resolution(raw: Any) -> tuple[int, int]:
    if not raw:
        return 6000, 4000
    s = str(raw).lower().replace(",", ".")
    for sep in ("×", "x"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) >= 2:
                nums_w = re.findall(r"\d+", parts[0])
                nums_h = re.findall(r"\d+", parts[1])
                if nums_w and nums_h:
                    try:
                        return int(nums_w[-1]), int(nums_h[0])
                    except ValueError:
                        pass
    nums = re.findall(r"\d+", s)
    if len(nums) >= 2:
        try:
            return int(nums[0]), int(nums[1])
        except ValueError:
            pass
    return 6000, 4000


def _parse_sensor_mm(raw: Any) -> tuple[float, float]:
    if not raw:
        return 23.5, 15.6
    s = str(raw).lower().replace(",", ".").replace("×", "x")
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    if len(nums) >= 2:
        try:
            w = float(nums[0])
            h = float(nums[1])
            if w > 2.0 and h > 2.0:
                return w, h
        except ValueError:
            pass
    m = re.search(r"1\s*/\s*(\d+(?:\.\d+)?)", s)
    if m:
        try:
            denom = float(m.group(1))
        except ValueError:
            return 23.5, 15.6
        for k in (f"1/{denom}", f"1/{denom:g}",
                  f"1/{int(denom)}" if denom.is_integer() else None):
            if k and k in _INCH_SENSOR_MM:
                return _INCH_SENSOR_MM[k]
        diag_mm = 25.4 / denom * 0.65
        return diag_mm * 4 / 5, diag_mm * 3 / 5
    return 23.5, 15.6


def _parse_focal_mm(raw: Any) -> float:
    if not raw:
        return 20.0
    s = str(raw).replace(",", ".").replace("=", " ")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 20.0


def _camera_params_from_catalog(camera: dict[str, Any]) -> dict[str, float]:
    """Парсит specs камеры. Особый случай — thermal-камеры."""
    specs = camera.get("specs", {})
    general = specs.get("general", {})
    perf = specs.get("performance", {})

    cam_type = str(general.get("type", "")).lower()

    if "thermal" in cam_type:
        sensor_raw = str(general.get("sensor", ""))
        res_w, res_h = 640, 512
        m = re.match(r"(\d+)\s*[x×]\s*(\d+)", sensor_raw)
        if m:
            res_w = int(m.group(1))
            res_h = int(m.group(2))

        lens = perf.get("lens", "F=9.1 mm")
        focal_mm = _parse_focal_mm(lens)

        try:
            pitch_um = float(general.get("pixel_pitch_um", 17.0))
        except (TypeError, ValueError):
            pitch_um = 17.0

        sensor_w_mm = res_w * pitch_um / 1000.0
        sensor_h_mm = res_h * pitch_um / 1000.0

        return {
            "sensor_w_mm": sensor_w_mm,
            "sensor_h_mm": sensor_h_mm,
            "res_w_px": res_w,
            "res_h_px": res_h,
            "focal_mm": focal_mm,
        }

    res_raw = (
        general.get("max_resolution")
        or general.get("resolution")
        or "6000x4000"
    )
    res_w, res_h = _parse_resolution(res_raw)

    sensor_raw = (
        general.get("sensor_size")
        or general.get("sensor")
        or "23.5x15.6"
    )
    sensor_w_mm, sensor_h_mm = _parse_sensor_mm(sensor_raw)

    focal_mm = _parse_focal_mm(perf.get("focal_length", "20"))

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
    overlap_x: float = 0.3,
    overlap_long: float = 0.7,
) -> dict[str, float]:
    gsd_m_per_px = gsd_cm_per_px / 100.0
    pixel_size_mm = camera_params["sensor_w_mm"] / camera_params["res_w_px"]

    h_agl_m = gsd_m_per_px * camera_params["focal_mm"] / pixel_size_mm
    swath_width_m = gsd_m_per_px * camera_params["res_w_px"]
    spacing_m = swath_width_m * (1.0 - overlap_x)

    frame_length_m = gsd_m_per_px * camera_params["res_h_px"]
    photo_interval_m = frame_length_m * (1.0 - overlap_long)

    return {
        "h_agl_m": h_agl_m,
        "swath_width_m": swath_width_m,
        "spacing_m": spacing_m,
        "frame_length_m": frame_length_m,
        "photo_interval_m": photo_interval_m,
    }


# ============================================================
# Сегменты
# ============================================================

def _segment_length_for(length_m: float) -> float:
    if length_m <= 100.0:
        return max(10.0, length_m / 5.0)
    return SEGMENT_LEN_M


def _make_segments(
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    length_m: float,
    h_agl_target: float,
    dem: BaseDEM | None,
    inv,
) -> list[SwathSegment]:
    seg_len = _segment_length_for(length_m)
    n_seg = max(1, int(np.ceil(length_m / seg_len)))
    segments: list[SwathSegment] = []

    for k in range(n_seg + 1):
        t = k / n_seg
        x = start_xy[0] + t * (end_xy[0] - start_xy[0])
        y = start_xy[1] + t * (end_xy[1] - start_xy[1])
        lon, lat = inv.transform(x, y)

        dem_h = dem.h(lat, lon) if dem is not None else 0.0
        h_asl = dem_h + h_agl_target

        segments.append(SwathSegment(
            lat=lat, lon=lon,
            h_agl_m=h_agl_target,
            h_asl_m=h_asl,
            dem_m=dem_h,
            dist_from_start_m=t * length_m,
        ))

    return segments


def _agl_min_over_segments(segments: list[SwathSegment]) -> float | None:
    if not segments:
        return None
    return float(min(s.h_asl_m - s.dem_m for s in segments))


def _avg_asl(segments: list[SwathSegment], n: int, from_start: bool) -> float:
    if not segments:
        return 0.0
    window = segments[:n] if from_start else segments[-n:]
    return float(np.mean([s.h_asl_m for s in window]))


# ============================================================
# Boustrophedon
# ============================================================

def _reverse_swath(s: Swath) -> Swath:
    new_start = Point(lat=s.end.lat, lon=s.end.lon, alt_m=s.end.alt_m)
    new_end = Point(lat=s.start.lat, lon=s.start.lon, alt_m=s.start.alt_m)

    total_len = s.length_m
    new_segments: list[SwathSegment] = []
    for seg in reversed(s.segments):
        new_segments.append(SwathSegment(
            lat=seg.lat, lon=seg.lon,
            h_agl_m=seg.h_agl_m,
            h_asl_m=seg.h_asl_m,
            dem_m=seg.dem_m,
            dist_from_start_m=total_len - seg.dist_from_start_m,
            v_ground_mps=seg.v_ground_mps,
        ))

    return Swath(
        id=s.id,
        area_id=s.area_id,
        start=new_start,
        end=new_end,
        length_m=s.length_m,
        segment_id=s.segment_id,
        h_agl_m=s.h_agl_m,
        h_asl_m=s.h_asl_m,
        segments=new_segments,
        h_asl_entry_m=s.h_asl_exit_m,
        h_asl_exit_m=s.h_asl_entry_m,
        h_agl_min_m=s.h_agl_min_m,
        dem_min_m=s.dem_min_m,
        dem_max_m=s.dem_max_m,
        t_survey_actual_s=s.t_survey_actual_s,
        e_survey_actual_wh=s.e_survey_actual_wh,
        v_survey_min_mps=s.v_survey_min_mps,
        feasible=s.feasible,
        infeasible_reason=s.infeasible_reason,
        n_photos=s.n_photos,
        frame_length_m=s.frame_length_m,
        photo_interval_m=s.photo_interval_m,
        parent_swath_id=s.parent_swath_id,
        sub_swath_index=s.sub_swath_index,
    )


def _apply_boustrophedon(swaths: list[Swath], fwd) -> list[Swath]:
    if len(swaths) < 2:
        return swaths

    def center_xy(s: Swath) -> tuple[float, float]:
        x1, y1 = fwd.transform(s.start.lon, s.start.lat)
        x2, y2 = fwd.transform(s.end.lon, s.end.lat)
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    x1, y1 = fwd.transform(swaths[0].start.lon, swaths[0].start.lat)
    x2, y2 = fwd.transform(swaths[0].end.lon, swaths[0].end.lat)
    dx, dy = x2 - x1, y2 - y1
    L = float(np.hypot(dx, dy))
    if L < 1e-6:
        return swaths
    px, py = -dy / L, dx / L

    def proj(s: Swath) -> float:
        cx, cy = center_xy(s)
        return cx * px + cy * py

    ordered = sorted(swaths, key=proj)

    result: list[Swath] = []
    for i, s in enumerate(ordered):
        if i % 2 == 1:
            result.append(_reverse_swath(s))
        else:
            result.append(s)
    return result


# ============================================================
# Split при крутом перепаде
# ============================================================

def _find_break_indices(
    segments: list[SwathSegment],
    v_nominal: float,
    v_climb: float,
    v_descent: float,
) -> list[int]:
    breaks = []
    for i in range(len(segments) - 1):
        seg_a = segments[i]
        seg_b = segments[i + 1]
        L = seg_b.dist_from_start_m - seg_a.dist_from_start_m
        if L <= 1e-6:
            continue
        dh = seg_b.h_asl_m - seg_a.h_asl_m
        v_rate = v_climb if dh > 0 else v_descent
        max_dh = v_rate * L / max(v_nominal, 0.5)
        if abs(dh) > max_dh + 1e-3:
            breaks.append(i)
    return breaks


def _make_sub_swath(
    parent: Swath,
    segments: list[SwathSegment],
    sub_index: int,
) -> Swath | None:
    if len(segments) < 2:
        return None

    first = segments[0]
    last = segments[-1]
    length_m = last.dist_from_start_m - first.dist_from_start_m
    if length_m <= 1e-6:
        return None

    h_asl_vals = [s.h_asl_m for s in segments]
    dem_vals = [s.dem_m for s in segments]

    n_avg = min(ENTRY_EXIT_AVG_N, len(segments))
    h_entry = _avg_asl(segments, n_avg, from_start=True)
    h_exit = _avg_asl(segments, n_avg, from_start=False)

    interval = max(parent.photo_interval_m, 1.0)
    n_photos = int(np.ceil(length_m / interval)) + 1

    return Swath(
        id=f"{parent.id}-p{sub_index}",
        area_id=parent.area_id,
        start=Point(lat=first.lat, lon=first.lon, alt_m=h_entry),
        end=Point(lat=last.lat, lon=last.lon, alt_m=h_exit),
        length_m=length_m,
        segment_id=parent.segment_id,
        h_agl_m=parent.h_agl_m,
        h_asl_m=float(np.mean(h_asl_vals)),
        segments=segments,
        h_asl_entry_m=h_entry,
        h_asl_exit_m=h_exit,
        h_agl_min_m=_agl_min_over_segments(segments),
        dem_min_m=float(min(dem_vals)),
        dem_max_m=float(max(dem_vals)),
        n_photos=n_photos,
        frame_length_m=parent.frame_length_m,
        photo_interval_m=parent.photo_interval_m,
        parent_swath_id=parent.id,
        sub_swath_index=sub_index,
    )


def split_swath_if_needed(
    swath: Swath,
    v_nominal: float,
    v_climb: float,
    v_descent: float,
) -> list[Swath]:
    if not swath.segments or len(swath.segments) < 2:
        return [swath]

    breaks = _find_break_indices(
        swath.segments, v_nominal, v_climb, v_descent,
    )
    if not breaks:
        return [swath]

    sub_swaths: list[Swath] = []
    start_idx = 0

    for br in breaks:
        chunk = swath.segments[start_idx:br + 1]
        s = _make_sub_swath(swath, chunk, len(sub_swaths))
        if s is not None:
            sub_swaths.append(s)
        start_idx = br + 1

    if start_idx < len(swath.segments):
        tail = swath.segments[start_idx:]
        if len(tail) >= 2:
            s = _make_sub_swath(swath, tail, len(sub_swaths))
            if s is not None:
                sub_swaths.append(s)
        elif not sub_swaths:
            return [swath]

    return sub_swaths if sub_swaths else [swath]


# ============================================================
# Время / энергия полосы
# ============================================================

def _compute_survey_time_energy(
    segments: list[SwathSegment],
    v_nominal: float,
    v_climb: float,
    v_descent: float,
    v_min: float,
    mass_kg: float,
    P_nominal_w: float,
) -> tuple[float, float, float, bool, str, int, float]:
    t_total = 0.0
    e_total_wh = 0.0
    v_min_used = v_nominal
    feasible = True
    reasons: list[str] = []
    n_infeasible = 0
    total_excess = 0.0

    for i in range(len(segments) - 1):
        seg_a = segments[i]
        seg_b = segments[i + 1]
        L = seg_b.dist_from_start_m - seg_a.dist_from_start_m
        if L <= 1e-6:
            continue
        dh = seg_b.h_asl_m - seg_a.h_asl_m

        if abs(dh) < 1e-6:
            v = v_nominal
        else:
            v_rate = v_climb if dh > 0 else v_descent
            v_needed = L * v_rate / abs(dh)
            if v_needed < v_min:
                feasible = False
                n_infeasible += 1
                if v_needed > 1e-6:
                    total_excess += v_min / v_needed - 1.0
                else:
                    total_excess += MAX_PENALTY_FACTOR
                reasons.append(
                    f"seg {i}->{i+1}: v_needed={v_needed:.2f} < "
                    f"v_min={v_min} (Δh={dh:+.1f}m, L={L:.0f}m)"
                )
                v = v_min
            else:
                v = min(v_nominal, v_needed)

        t_seg = L / v
        t_total += t_seg

        P = P_nominal_w
        if dh > 0:
            P += mass_kg * G * dh / max(t_seg, 0.1)

        e_total_wh += P * t_seg / 3600.0
        v_min_used = min(v_min_used, v)
        seg_a.v_ground_mps = v

    if segments:
        segments[-1].v_ground_mps = v_nominal

    if total_excess > 0.0:
        penalty = 1.0 + min(total_excess, MAX_PENALTY_FACTOR)
        t_total *= penalty
        e_total_wh *= penalty

    reason = "; ".join(reasons)
    return (t_total, e_total_wh, v_min_used, feasible, reason,
            n_infeasible, total_excess)


# ============================================================
# Разбиение MultiPolygon
# ============================================================

def _polygon_components(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return [g for g in geom.geoms if not g.is_empty]
    if geom.geom_type == "GeometryCollection":
        return [
            g for g in geom.geoms
            if g.geom_type == "Polygon" and not g.is_empty
        ]
    return []


# ============================================================
# Генерация линий — F2C vs legacy
# ============================================================

def _generate_lines_f2c(
    comp_m: Polygon,
    spacing_m: float,
    headland_width_m: float,
) -> list[LineString]:
    from planner.geometry.f2c_backend import (
        generate_swaths_f2c, is_available,
    )
    if not is_available():
        raise RuntimeError("fields2cover not available")
    return generate_swaths_f2c(
        comp_m, spacing_m, headland_width_m,
    )


def _generate_lines_legacy(
    comp_rot: Polygon,
    decomposition: str,
    spacing_m: float,
) -> list[LineString]:
    if decomposition == "triangulation":
        pieces = triangulation_decomposition(comp_rot)
    else:
        pieces = trapezoid_decomposition(comp_rot)

    lines: list[LineString] = []
    for piece in pieces:
        lines.extend(
            swaths_in_piece(piece, angle_deg=0.0, spacing_m=spacing_m)
        )
    return lines


# ============================================================
# Основная функция
# ============================================================

def generate_swaths_for_area(
    area: Area,
    obstacles: list[Obstacle],
    angle_deg: float,
    gsd_cm_per_px: float,
    camera: dict[str, Any],
    decomposition: str = "trapezoid",
    overlap_x: float = 0.3,
    overlap_long: float = 0.7,
    dem: BaseDEM | None = None,
    v_climb_mps: float = 3.0,
    v_descent_mps: float = 3.0,
    v_min_mps: float = 1.0,
    v_survey_mps: float = 12.0,
    mass_kg: float = 2.0,
    P_nominal_w: float = 300.0,
    obstacle_buffer_m: float = 20.0,
    headland_width_m: float = 0.0,
    no_fly_zones: list[NoFlyZone] | None = None,
    no_fly_buffer_m: float = 0.0,
) -> tuple[list[Swath], float]:
    """Генерирует полосы для области.

    Препятствия вычитаются с obstacle_buffer_m. Запретные зоны —
    всегда, с no_fly_buffer_m (по умолчанию 0). Препятствия
    летать «над» в этой версии НЕЛЬЗЯ (как и было).
    """
    no_fly_zones = no_fly_zones or []

    cam = _camera_params_from_catalog(camera)
    geom_calc = compute_flight_and_swath(
        gsd_cm_per_px, cam, overlap_x, overlap_long,
    )
    h_agl_target = geom_calc["h_agl_m"]
    spacing_m = geom_calc["spacing_m"]
    frame_length_m = geom_calc["frame_length_m"]
    photo_interval_m = geom_calc["photo_interval_m"]

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

    # 1. Запретные зоны — вычитаем ВСЕГДА
    for nfz in no_fly_zones:
        nfz_poly = shape(nfz.polygon)
        nfz_m = Polygon(
            [fwd.transform(x, y) for x, y in nfz_poly.exterior.coords]
        )
        if no_fly_buffer_m > 0:
            nfz_m = nfz_m.buffer(no_fly_buffer_m)
        poly_m = poly_m.difference(nfz_m)

    # 2. Препятствия — вычитаем с буфером
    for obs in obstacles:
        obs_poly = shape(obs.polygon)
        obs_m = Polygon(
            [fwd.transform(x, y) for x, y in obs_poly.exterior.coords]
        )
        if obstacle_buffer_m > 0:
            obs_m = obs_m.buffer(obstacle_buffer_m)
        poly_m = poly_m.difference(obs_m)

    if poly_m.is_empty:
        return [], h_agl_target

    components_m = _polygon_components(poly_m)
    if not components_m:
        return [], h_agl_target

    if len(components_m) == 1:
        cx, cy = components_m[0].centroid.x, components_m[0].centroid.y
    else:
        total_area = sum(p.area for p in components_m)
        if total_area > 0:
            cx = sum(p.centroid.x * p.area for p in components_m) / total_area
            cy = sum(p.centroid.y * p.area for p in components_m) / total_area
        else:
            cx = sum(p.centroid.x for p in components_m) / len(components_m)
            cy = sum(p.centroid.y for p in components_m) / len(components_m)

    use_f2c = False
    if decomposition in ("fields2cover", "auto"):
        from planner.geometry.f2c_backend import is_available
        use_f2c = is_available()
        if not use_f2c and decomposition == "fields2cover":
            log_warn(
                "geometry",
                "fields2cover not available, falling back to trapezoid",
            )

    base_swaths: list[Swath] = []
    sid = 0

    for comp in components_m:
        if use_f2c:
            try:
                lines_original = _generate_lines_f2c(
                    comp, spacing_m, headland_width_m,
                )
            except Exception as e:
                log_warn(
                    "geometry",
                    f"F2C failed on component (area={comp.area:.0f} m²): "
                    f"{type(e).__name__}: {e} — fallback on trapezoid",
                )
                comp_rot = rotate(comp, -angle_deg, origin=(cx, cy))
                lines_rot = _generate_lines_legacy(
                    comp_rot, "trapezoid", spacing_m,
                )
                lines_original = [
                    rotate(ln, angle_deg, origin=(cx, cy))
                    for ln in lines_rot
                ]
        else:
            comp_rot = rotate(comp, -angle_deg, origin=(cx, cy))
            lines_rot = _generate_lines_legacy(
                comp_rot, decomposition, spacing_m,
            )
            lines_original = [
                rotate(ln, angle_deg, origin=(cx, cy))
                for ln in lines_rot
            ]

        for line in lines_original:
            coords = list(line.coords)
            if len(coords) < 2:
                continue

            start_xy = coords[0]
            end_xy = coords[-1]
            length_m = float(line.length)
            if length_m < MIN_SWATH_LEN_M:
                continue

            segments = _make_segments(
                start_xy=start_xy,
                end_xy=end_xy,
                length_m=length_m,
                h_agl_target=h_agl_target,
                dem=dem,
                inv=inv,
            )

            h_vals = [s.h_asl_m for s in segments]
            dem_vals = [s.dem_m for s in segments]

            n_avg = min(ENTRY_EXIT_AVG_N, len(segments))
            h_entry = _avg_asl(segments, n_avg, from_start=True)
            h_exit = _avg_asl(segments, n_avg, from_start=False)

            n_photos = int(np.ceil(length_m / max(photo_interval_m, 1.0))) + 1

            base_swaths.append(Swath(
                id=f"{area.id}-s{sid}",
                area_id=area.id,
                start=Point(lat=segments[0].lat, lon=segments[0].lon,
                            alt_m=h_entry),
                end=Point(lat=segments[-1].lat, lon=segments[-1].lon,
                          alt_m=h_exit),
                length_m=length_m,
                h_agl_m=h_agl_target,
                h_asl_m=float(np.mean(h_vals)),
                segments=segments,
                h_asl_entry_m=h_entry,
                h_asl_exit_m=h_exit,
                h_agl_min_m=_agl_min_over_segments(segments),
                dem_min_m=float(min(dem_vals)),
                dem_max_m=float(max(dem_vals)),
                n_photos=n_photos,
                frame_length_m=frame_length_m,
                photo_interval_m=photo_interval_m,
            ))
            sid += 1

    base_swaths = _apply_boustrophedon(base_swaths, fwd)

    final_swaths: list[Swath] = []
    for base in base_swaths:
        parts = split_swath_if_needed(
            base,
            v_nominal=v_survey_mps,
            v_climb=v_climb_mps,
            v_descent=v_descent_mps,
        )
        for part in parts:
            (t_s, e_wh, v_min_used, feasible, reason,
             n_infeasible, total_excess) = _compute_survey_time_energy(
                segments=part.segments,
                v_nominal=v_survey_mps,
                v_climb=v_climb_mps,
                v_descent=v_descent_mps,
                v_min=v_min_mps,
                mass_kg=mass_kg,
                P_nominal_w=P_nominal_w,
            )
            part.t_survey_actual_s = t_s
            part.e_survey_actual_wh = e_wh
            part.v_survey_min_mps = v_min_used
            part.feasible = feasible
            if n_infeasible > 0:
                penalty = 1.0 + min(total_excess, MAX_PENALTY_FACTOR)
                part.infeasible_reason = (
                    f"{reason} | penalty ×{penalty:.2f} "
                    f"(n_infeasible={n_infeasible}, "
                    f"excess={total_excess:.2f})"
                )
            else:
                part.infeasible_reason = reason
            final_swaths.append(part)

    return final_swaths, h_agl_target