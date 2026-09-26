"""Генерация полос с разбиением при крутых перепадах рельефа
и boustrophedon-порядком (reverse нечётных)."""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely.geometry import Polygon, shape

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.io.dem import BaseDEM
from planner.models import Area, Obstacle, Point, Swath, SwathSegment
from planner.utils.geo import make_local_transformer


SEGMENT_LEN_M = 30.0
G = 9.81


# ============================================================
# Камера / GSD
# ============================================================

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


# ============================================================
# Сегменты
# ============================================================

def _make_segments(
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    length_m: float,
    h_agl_target: float,
    dem: DEM | None,
    inv,
) -> list[SwathSegment]:
    """Разбивает полосу на сегменты по SEGMENT_LEN_M."""
    n_seg = max(1, int(np.ceil(length_m / SEGMENT_LEN_M)))
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


# ============================================================
# Boustrophedon: сортировка + reverse нечётных
# ============================================================

def _reverse_swath(s: Swath) -> Swath:
    """Меняет направление полосы: start ↔ end, segments reverse."""
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
        parent_swath_id=s.parent_swath_id,
        sub_swath_index=s.sub_swath_index,
    )


def _apply_boustrophedon(swaths: list[Swath], fwd) -> list[Swath]:
    """
    1. Сортирует полосы по проекции центра на перпендикуляр к направлению полос.
    2. Чередует направление (чётные — как есть, нечётные — reverse).
    """
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
# Разбиение при крутом перепаде
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


def _make_sub_swath(parent: Swath, segments: list[SwathSegment], sub_index: int) -> Swath:
    first = segments[0]
    last = segments[-1]
    length_m = last.dist_from_start_m - first.dist_from_start_m

    h_asl_vals = [s.h_asl_m for s in segments]
    dem_vals = [s.dem_m for s in segments]

    return Swath(
        id=f"{parent.id}-p{sub_index}",
        area_id=parent.area_id,
        start=Point(lat=first.lat, lon=first.lon, alt_m=first.h_asl_m),
        end=Point(lat=last.lat, lon=last.lon, alt_m=last.h_asl_m),
        length_m=length_m,
        segment_id=parent.segment_id,
        h_agl_m=parent.h_agl_m,
        h_asl_m=float(np.mean(h_asl_vals)),
        segments=segments,
        h_asl_entry_m=first.h_asl_m,
        h_asl_exit_m=last.h_asl_m,
        h_agl_min_m=min(s.h_agl_m for s in segments),
        dem_min_m=float(min(dem_vals)),
        dem_max_m=float(max(dem_vals)),
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
        if len(chunk) >= 2:
            sub_swaths.append(_make_sub_swath(swath, chunk, len(sub_swaths)))
        start_idx = br + 1

    if start_idx < len(swath.segments):
        tail = swath.segments[start_idx:]
        if len(tail) >= 2:
            sub_swaths.append(_make_sub_swath(swath, tail, len(sub_swaths)))
        elif sub_swaths and tail:
            last = sub_swaths[-1]
            last.segments.extend(tail)
            last.end = Point(lat=tail[-1].lat, lon=tail[-1].lon,
                             alt_m=tail[-1].h_asl_m)
            last.length_m = (
                last.segments[-1].dist_from_start_m
                - last.segments[0].dist_from_start_m
            )
            last.h_asl_exit_m = tail[-1].h_asl_m

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
) -> tuple[float, float, float, bool, str]:
    t_total = 0.0
    e_total_wh = 0.0
    v_min_used = v_nominal
    feasible = True
    reason = ""

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
                reason = (
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

    return t_total, e_total_wh, v_min_used, feasible, reason


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
    overlap: float = 0.3,
    dem: BaseDEM | None = None,
    v_climb_mps: float = 3.0,
    v_descent_mps: float = 3.0,
    v_min_mps: float = 1.0,
    v_survey_mps: float = 12.0,
    mass_kg: float = 2.0,
    P_nominal_w: float = 300.0,
) -> tuple[list[Swath], float]:
    """Возвращает (swaths, h_agl_target)."""
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

    # 1. Базовые полосы (без split)
    base_swaths: list[Swath] = []
    sid = 0

    for piece in pieces:
        for line in swaths_in_piece(piece, angle_deg=angle_deg, spacing_m=spacing_m):
            coords = list(line.coords)
            if len(coords) < 2:
                continue
            start_xy = coords[0]
            end_xy = coords[-1]
            length_m = float(line.length)
            if length_m < 5.0:
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

            base_swaths.append(Swath(
                id=f"{area.id}-s{sid}",
                area_id=area.id,
                start=Point(lat=segments[0].lat, lon=segments[0].lon,
                            alt_m=segments[0].h_asl_m),
                end=Point(lat=segments[-1].lat, lon=segments[-1].lon,
                          alt_m=segments[-1].h_asl_m),
                length_m=length_m,
                h_agl_m=h_agl_target,
                h_asl_m=float(np.mean(h_vals)),
                segments=segments,
                h_asl_entry_m=segments[0].h_asl_m,
                h_asl_exit_m=segments[-1].h_asl_m,
                h_agl_min_m=min(s.h_agl_m for s in segments),
                dem_min_m=float(min(dem_vals)),
                dem_max_m=float(max(dem_vals)),
            ))
            sid += 1

    # 2. Boustrophedon: сортировка + reverse нечётных
    base_swaths = _apply_boustrophedon(base_swaths, fwd)

    # 3. Split + расчёт времени/энергии
    final_swaths: list[Swath] = []
    for base in base_swaths:
        parts = split_swath_if_needed(
            base,
            v_nominal=v_survey_mps,
            v_climb=v_climb_mps,
            v_descent=v_descent_mps,
        )
        for part in parts:
            t_s, e_wh, v_min_used, feasible, reason = (
                _compute_survey_time_energy(
                    segments=part.segments,
                    v_nominal=v_survey_mps,
                    v_climb=v_climb_mps,
                    v_descent=v_descent_mps,
                    v_min=v_min_mps,
                    mass_kg=mass_kg,
                    P_nominal_w=P_nominal_w,
                )
            )
            part.t_survey_actual_s = t_s
            part.e_survey_actual_wh = e_wh
            part.v_survey_min_mps = v_min_used
            part.feasible = feasible
            part.infeasible_reason = reason
            final_swaths.append(part)

    return final_swaths, h_agl_target