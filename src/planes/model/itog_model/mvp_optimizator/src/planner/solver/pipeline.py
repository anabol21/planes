"""Основной конвейер: от MissionInput до Report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from planner.geometry.generate import generate_swaths_for_area
from planner.io.catalog import Catalog, get_default_catalog
from planner.io.loaders import load_mission
from planner.models import (
    Candidate,
    Criterion,
    DecompositionMethod,
    Metrics,
    MissionInput,
    Point,
    Report,
    Route,
    Swath,
    UAVSummary,
)
from planner.physics import build_physics_model, build_physics_params
from planner.physics.base import PhysicsParams
from planner.solver.assignment import assign_clusters_to_uavs
from planner.solver.clustering import cluster_swaths
from planner.solver.counters import Counters
from planner.solver.multi_flight import solve_multi_flight
from planner.solver.obstacles import prepare_obstacles_m, shortest_path_avoiding
from planner.solver.routing import RoutingResult
from planner.utils.geo import make_local_transformer
from planner.utils.logging import log_debug, log_info, log_warn
from planner.utils.route_metrics import recalc_all_routes
from planner.utils.spline import smooth_waypoints
from planner.utils.terrain_following import terrain_corridor, terrain_range_m
from planner.validator import validate


# Пороги для логирования raised waypoints.
_RAISED_DEBUG_MAX = 5
_RAISED_INFO_MAX = 50

# Ускорение свободного падения — для энергии вертикального подъёма.
_G = 9.81


@dataclass
class MissionContext:
    mission: MissionInput
    catalog: object
    swaths_by_area: dict[str, list]
    h_agl_by_area: dict[str, float]
    params_by_uav: dict[str, PhysicsParams]


# ============================================================
# Максимальная взлётная масса
# ============================================================

def _max_takeoff_mass_kg(
    catalog: Catalog, uav_model: str
) -> float | None:
    """Читает m_max из каталога: max_takeoff_mass, иначе weight."""
    try:
        aircraft = catalog.get_aircraft(uav_model)
    except KeyError:
        return None

    general = aircraft.get("specs", {}).get("general", {})
    raw = general.get("max_takeoff_mass") or general.get("weight")
    if not raw:
        return None

    for token in str(raw).split():
        try:
            return float(token)
        except ValueError:
            continue
    return None


# ============================================================
# Динамический safety margin
# ============================================================

def _effective_safety_margin(
    base_margin_m: float,
    factor: float,
    waypoints: list[Point] | None,
    dem,
) -> float:
    """Финальный safety margin: max(base, terrain_range · factor)."""
    if factor <= 0.0 or dem is None or not waypoints:
        return base_margin_m

    rng = terrain_range_m(waypoints, dem)
    if rng <= 0.0:
        return base_margin_m

    return max(base_margin_m, rng * factor)


# ============================================================
# Генерация полос
# ============================================================

def _generate_all_swaths(
    mission: MissionInput,
    angle_deg: float,
) -> tuple[dict[str, list], dict[str, float]]:
    catalog = get_default_catalog()
    uav = mission.uavs[0]
    camera = catalog.get_camera(uav.camera_id)

    pp = build_physics_params(
        uav, catalog, reserve_fraction=mission.params.reserve_fraction
    )
    model = build_physics_model(pp)
    P_nominal = model.power_w(pp.v_air_mps, mission.params.wind.speed_mps)

    swaths_by_area: dict[str, list] = {}
    h_agl_by_area: dict[str, float] = {}

    for area in mission.areas:
        swaths, h_agl = generate_swaths_for_area(
            area=area,
            obstacles=mission.obstacles,
            angle_deg=angle_deg,
            gsd_cm_per_px=mission.params.gsd_cm_per_px,
            camera=camera,
            decomposition=mission.params.decomposition.value,
            overlap_x=mission.params.overlap_x,
            overlap_long=mission.params.overlap_long,
            dem=mission.dem,
            v_climb_mps=pp.v_climb_mps,
            v_descent_mps=pp.v_descent_mps,
            v_min_mps=pp.v_min_mps,
            v_survey_mps=pp.v_survey_mps,
            mass_kg=pp.mass_kg,
            P_nominal_w=P_nominal,
            obstacle_buffer_m=mission.params.obstacle_buffer_m,
            headland_width_m=mission.params.fields2cover_headland_m,
        )
        swaths_by_area[area.id] = swaths
        h_agl_by_area[area.id] = h_agl

    return swaths_by_area, h_agl_by_area


# ============================================================
# Маршрутизация одного борта
# ============================================================

def _solve_for_uav(
    uav_id: str,
    swath_ids: list[str],
    swaths_by_id: dict,
    vpp,
    fwd,
    physics,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
    h_agl_m: float,
    R_max: int,
    obstacles_m: list,
) -> list[RoutingResult]:
    swaths = [swaths_by_id[sid] for sid in swath_ids]
    return solve_multi_flight(
        uav_id=uav_id,
        swaths=swaths,
        vpp=vpp,
        fwd=fwd,
        physics=physics,
        params=params,
        wind_speed_mps=wind_speed_mps,
        wind_direction_deg=wind_direction_deg,
        h_agl_m=h_agl_m,
        R_max=R_max,
        obstacles_m=obstacles_m,
    )


# ============================================================
# Waypoints с slope-constraint
# ============================================================

def _append_transition(
    waypoints: list[Point],
    wps_xy: list[tuple[float, float]],
    h_from: float,
    h_to: float,
    inv,
    v_climb_mps: float = 5.0,
    v_ground_mps: float = 12.0,
) -> float:
    """Добавляет переход между двумя точками с ограничением уклона.

    Если dh_total влезает в slope-constraint на длине total_d —
    линейная интерполяция, extra_climb = 0.

    Если не влезает — набираем по максимальному уклону, оставшуюся
    высоту добираем вертикально в конце. Возвращает extra_climb_m —
    сколько метров довесили.

    Returns:
        extra_climb_m — высота, пройденная вертикально (0 если не нужно).
    """
    if len(wps_xy) < 2:
        return 0.0

    cum_d = [0.0]
    for k in range(len(wps_xy) - 1):
        dx = wps_xy[k + 1][0] - wps_xy[k][0]
        dy = wps_xy[k + 1][1] - wps_xy[k][1]
        cum_d.append(cum_d[-1] + float(np.hypot(dx, dy)))

    total_d = cum_d[-1]
    if total_d < 1e-6:
        return 0.0

    dh_total = h_to - h_from
    max_slope = v_climb_mps / max(v_ground_mps, 0.5)
    max_dh_on_path = max_slope * total_d

    if abs(dh_total) <= max_dh_on_path:
        # Влезает — линейная интерполяция
        for k in range(1, len(wps_xy)):
            t = cum_d[k] / total_d
            h = h_from + dh_total * t
            lon, lat = inv.transform(wps_xy[k][0], wps_xy[k][1])
            waypoints.append(Point(lat=lat, lon=lon, alt_m=h))
        return 0.0

    # Не влезает — набираем по максимальному уклону
    sign = 1.0 if dh_total > 0 else -1.0
    dh_on_path = sign * max_dh_on_path

    for k in range(1, len(wps_xy)):
        t = cum_d[k] / total_d
        h = h_from + dh_on_path * t
        lon, lat = inv.transform(wps_xy[k][0], wps_xy[k][1])
        waypoints.append(Point(lat=lat, lon=lon, alt_m=h))

    # Остаток высоты — вертикально в конце (2 точки на одной xy)
    h_reached = h_from + dh_on_path
    dh_left = h_to - h_reached
    if abs(dh_left) > 0.1:
        last_lon, last_lat = inv.transform(wps_xy[-1][0], wps_xy[-1][1])
        waypoints.append(Point(lat=last_lat, lon=last_lon,
                               alt_m=h_reached + dh_left / 2.0))
        waypoints.append(Point(lat=last_lat, lon=last_lon,
                               alt_m=h_to))
        return abs(dh_left)

    return 0.0


def _swath_entry_height(s: Swath) -> float:
    """Высота входа в полосу. 0.0 ASL — валидное значение."""
    if s.h_asl_entry_m is not None:
        return s.h_asl_entry_m
    return s.h_asl_m


def _swath_exit_height(s: Swath) -> float:
    """Высота выхода из полосы."""
    if s.h_asl_exit_m is not None:
        return s.h_asl_exit_m
    return s.h_asl_m


def _compute_route_waypoints(
    swath_ids: list[str],
    swaths_by_id: dict,
    vpp,
    fwd,
    inv,
    obstacles_m: list,
    dem=None,
    safety_margin_m: float = 0.0,
    v_climb_mps: float = 5.0,
    v_ground_mps: float = 12.0,
) -> tuple[list[Point], int, float]:
    """Строит waypoints маршрута.

    Returns:
        (waypoints, n_raised, extra_climb_m).
    """
    vpp_xy = fwd.transform(vpp.lon, vpp.lat)
    waypoints: list[Point] = [
        Point(lat=vpp.lat, lon=vpp.lon, alt_m=vpp.alt_m)
    ]

    prev_xy = vpp_xy
    prev_h = vpp.alt_m
    total_extra_climb = 0.0

    for sid in swath_ids:
        s = swaths_by_id.get(sid)
        if s is None:
            continue

        entry_xy = fwd.transform(s.start.lon, s.start.lat)
        h_entry = _swath_entry_height(s)

        _, wps = shortest_path_avoiding(prev_xy, entry_xy, obstacles_m)
        total_extra_climb += _append_transition(
            waypoints, wps, prev_h, h_entry, inv,
            v_climb_mps=v_climb_mps, v_ground_mps=v_ground_mps,
        )

        if s.segments and len(s.segments) >= 2:
            for seg in s.segments:
                waypoints.append(Point(lat=seg.lat, lon=seg.lon,
                                       alt_m=seg.h_asl_m))
        else:
            waypoints.append(Point(lat=s.start.lat, lon=s.start.lon,
                                   alt_m=h_entry))
            waypoints.append(Point(lat=s.end.lat, lon=s.end.lon,
                                   alt_m=_swath_exit_height(s)))

        prev_xy = fwd.transform(s.end.lon, s.end.lat)
        prev_h = _swath_exit_height(s)

    _, wps = shortest_path_avoiding(prev_xy, vpp_xy, obstacles_m)
    total_extra_climb += _append_transition(
        waypoints, wps, prev_h, vpp.alt_m, inv,
        v_climb_mps=v_climb_mps, v_ground_mps=v_ground_mps,
    )

    n_raised = 0
    if dem is not None and safety_margin_m > 0:
        if not getattr(dem, "is_empty", lambda: True)():
            for wp in waypoints:
                dem_h = dem.h(wp.lat, wp.lon)
                h_agl = wp.alt_m - dem_h
                if h_agl < safety_margin_m:
                    wp.alt_m = dem_h + safety_margin_m
                    n_raised += 1

    return waypoints, n_raised, total_extra_climb


# ============================================================
# Terrain corridor / spline
# ============================================================

def _apply_terrain_corridor(
    waypoints: list[Point],
    dem,
    h_agl_target_m: float,
    safety_margin_m: float,
    smooth_window: int = 5,
) -> list[Point]:
    if not waypoints or dem is None:
        return waypoints

    try:
        if dem.is_empty():
            return waypoints
    except AttributeError:
        return waypoints

    smoothed = terrain_corridor(
        waypoints=waypoints,
        dem=dem,
        h_agl_target_m=h_agl_target_m,
        safety_margin_m=safety_margin_m,
        smooth_window=smooth_window,
    )

    for wp in smoothed:
        dem_h = dem.h(wp.lat, wp.lon)
        h_agl = wp.alt_m - dem_h
        if h_agl < safety_margin_m:
            wp.alt_m = dem_h + safety_margin_m

    return smoothed


def _apply_smoothing(
    waypoints: list[Point],
    dem=None,
    safety_margin_m: float = 0.0,
    n_samples: int = 300,
) -> tuple[list[Point], int]:
    if len(waypoints) < 3:
        return waypoints, 0

    smoothed = smooth_waypoints(waypoints, n_samples=n_samples)

    n_raised = 0
    if dem is not None and safety_margin_m > 0:
        if not getattr(dem, "is_empty", lambda: True)():
            for wp in smoothed:
                dem_h = dem.h(wp.lat, wp.lon)
                h_agl = wp.alt_m - dem_h
                if h_agl < safety_margin_m:
                    wp.alt_m = dem_h + safety_margin_m
                    n_raised += 1

    return smoothed, n_raised


def _log_raised(
    block: str, n_raised: int, stage: str, **extra
) -> None:
    """Логирует raised waypoints с уровнем по количеству."""
    msg = f"raised {n_raised} waypoints {stage}"
    if n_raised <= _RAISED_DEBUG_MAX:
        log_debug(block, msg, n_raised=n_raised, **extra)
    elif n_raised <= _RAISED_INFO_MAX:
        log_info(block, msg, n_raised=n_raised, **extra)
    else:
        log_warn(block, msg, n_raised=n_raised, **extra)


# ============================================================
# Candidate
# ============================================================

def _build_candidate(
    theta_deg: float,
    all_routes: list[Route],
    decomposition_method: DecompositionMethod,
) -> Candidate | None:
    if not all_routes:
        return None

    by_uav: dict[str, list[Route]] = {}
    for r in all_routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    C_max_per_uav: list[float] = []
    for uav_id, routes in by_uav.items():
        sorted_r = sorted(routes, key=lambda x: x.flight_index)
        T_charge = sorted_r[0].T_charge_s if sorted_r else 0.0
        total = sum(r.T_total_s for r in sorted_r)
        total += max(0, len(sorted_r) - 1) * T_charge
        C_max_per_uav.append(total)

    return Candidate(
        theta_deg=theta_deg,
        C_max_s=max(C_max_per_uav) if C_max_per_uav else 0.0,
        flight_hours_s=sum(r.T_air_s for r in all_routes),
        energy_total_wh=sum(r.E_wh for r in all_routes),
        n_uavs_used=len(by_uav),
        routes=all_routes,
        decomposition_method=decomposition_method,
    )


# ============================================================
# Прогон одного угла
# ============================================================

def run_one_angle(
    mission: MissionInput,
    angle_deg: float,
    counters: Counters,
    swaths_by_area: dict[str, list] | None = None,
    h_agl_by_area: dict[str, float] | None = None,
    max_takeoff_mass_kg: float | None = None,
) -> Candidate | None:
    catalog = get_default_catalog()

    if swaths_by_area is None or h_agl_by_area is None:
        swaths_by_area, h_agl_by_area = _generate_all_swaths(mission, angle_deg)

    all_swaths = [s for sw in swaths_by_area.values() for s in sw]
    if not all_swaths:
        log_warn("pipeline", "no swaths generated", theta=angle_deg)
        return None

    swaths_by_id = {s.id: s for s in all_swaths}

    clusters = cluster_swaths(all_swaths, k=len(mission.uavs))
    assign = assign_clusters_to_uavs(clusters, mission.uavs, mission.vpps)

    params_by_uav: dict[str, PhysicsParams] = {}
    physics_by_uav = {}
    P_nominal_by_uav: dict[str, float] = {}
    for uav in mission.uavs:
        pp = build_physics_params(
            uav, catalog, reserve_fraction=mission.params.reserve_fraction
        )
        params_by_uav[uav.id] = pp
        model = build_physics_model(pp)
        physics_by_uav[uav.id] = model
        P_nominal_by_uav[uav.id] = model.power_w(
            pp.v_air_mps, mission.params.wind.speed_mps
        )

    all_routes: list[Route] = []
    extra_climb_by_route: list[float] = []

    wind_speed = mission.params.wind.speed_mps
    wind_dir = mission.params.wind.direction_deg
    h_agl_m = sum(h_agl_by_area.values()) / max(len(h_agl_by_area), 1)

    base_margin = mission.params.safety_margin_m
    factor = mission.params.safety_margin_factor
    if factor > 0.0 and mission.dem is not None:
        probe_points = []
        for s in all_swaths:
            probe_points.append(
                Point(lat=s.start.lat, lon=s.start.lon, alt_m=0.0)
            )
            probe_points.append(
                Point(lat=s.end.lat, lon=s.end.lon, alt_m=0.0)
            )
        effective_margin = _effective_safety_margin(
            base_margin, factor, probe_points, mission.dem,
        )
    else:
        effective_margin = base_margin

    if effective_margin != base_margin:
        log_info(
            "pipeline",
            f"safety margin adjusted: {base_margin} → "
            f"{effective_margin:.1f} m",
            theta=angle_deg,
            factor=factor,
        )

    for uav in mission.uavs:
        uav_clusters = assign.get(uav.id, [])
        swath_ids = [sid for c in uav_clusters for sid in c.swath_ids]
        if not swath_ids:
            continue

        vpp = mission.vpp_by_id(uav.vpp_id)
        fwd, inv = make_local_transformer(vpp.lon, vpp.lat)

        obs_geojsons = [o.polygon for o in mission.obstacles]
        obstacles_m = prepare_obstacles_m(obs_geojsons, fwd)

        pp_current = params_by_uav[uav.id]

        results = _solve_for_uav(
            uav_id=uav.id,
            swath_ids=swath_ids,
            swaths_by_id=swaths_by_id,
            vpp=vpp,
            fwd=fwd,
            physics=physics_by_uav[uav.id],
            params=pp_current,
            wind_speed_mps=wind_speed,
            wind_direction_deg=wind_dir,
            h_agl_m=h_agl_m,
            R_max=mission.params.R_max,
            obstacles_m=obstacles_m,
        )

        T_charge = pp_current.T_charge_s

        for i, res in enumerate(results):
            waypoints, n_raised, extra_climb_m = _compute_route_waypoints(
                swath_ids=res.swath_ids,
                swaths_by_id=swaths_by_id,
                vpp=vpp,
                fwd=fwd,
                inv=inv,
                obstacles_m=obstacles_m,
                dem=mission.dem,
                safety_margin_m=effective_margin,
                v_climb_mps=pp_current.v_climb_mps,
                v_ground_mps=pp_current.v_air_mps,
            )
            if n_raised > 0:
                _log_raised(
                    "pipeline", n_raised, "for terrain safety",
                    uav=uav.id, flight=i, theta=angle_deg,
                )

            if extra_climb_m > 0.5:
                log_debug(
                    "pipeline",
                    f"extra vertical climb: {extra_climb_m:.1f} m",
                    uav=uav.id, flight=i, theta=angle_deg,
                )

            if mission.params.terrain_corridor and mission.dem is not None:
                waypoints = _apply_terrain_corridor(
                    waypoints=waypoints,
                    dem=mission.dem,
                    h_agl_target_m=h_agl_m,
                    safety_margin_m=effective_margin,
                    smooth_window=mission.params.terrain_smooth_window,
                )

            n_raised_after = 0
            if mission.params.smooth_waypoints and len(waypoints) >= 3:
                waypoints, n_raised_after = _apply_smoothing(
                    waypoints=waypoints,
                    dem=mission.dem,
                    safety_margin_m=effective_margin,
                    n_samples=mission.params.spline_samples,
                )
                if n_raised_after > 0:
                    _log_raised(
                        "pipeline", n_raised_after, "after spline",
                        uav=uav.id, flight=i, theta=angle_deg,
                    )

            all_routes.append(Route(
                uav_id=uav.id,
                flight_index=i,
                vpp_id=res.vpp_id,
                swath_ids=res.swath_ids,
                T_air_s=res.T_air_s,
                T_total_s=res.T_total_s,
                E_wh=res.E_wh,
                mass_kg=pp_current.mass_kg,
                T_charge_s=T_charge,
                waypoints=waypoints,
            ))
            extra_climb_by_route.append(extra_climb_m)

    if not all_routes:
        log_warn("pipeline", "no routes", theta=angle_deg)
        return None

    recalc_all_routes(
        routes=all_routes,
        params_by_uav=params_by_uav,
        wind_speed_mps=wind_speed,
        wind_direction_deg=wind_dir,
        P_nominal_by_uav=P_nominal_by_uav,
    )

    # После recalc — учесть вертикальные подъёмы (extra_climb_m).
    for r, extra_climb_m in zip(all_routes, extra_climb_by_route):
        if extra_climb_m <= 0.0:
            continue
        pp = params_by_uav.get(r.uav_id)
        if pp is None:
            continue
        v_climb = max(pp.v_climb_mps, 0.5)
        t_extra = extra_climb_m / v_climb
        e_extra = pp.mass_kg * _G * extra_climb_m / 3600.0
        r.T_air_s += t_extra
        r.T_total_s += t_extra
        r.E_wh += e_extra

    result = validate(
        mission=mission,
        all_swaths=all_swaths,
        routes=all_routes,
        params_by_uav=params_by_uav,
        max_takeoff_mass_kg=max_takeoff_mass_kg,
        strict_terrain_check=mission.params.strict_terrain_check,
    )

    if not result.valid:
        log_warn(
            "pipeline",
            f"validation failed: {result.errors[:3]}",
            theta=angle_deg,
            n_errors=len(result.errors),
        )
        counters.inc_attempts()
        return None

    if result.warnings:
        for w in result.warnings:
            log_warn("pipeline", w, theta=angle_deg)

    log_info(
        "pipeline",
        f"angle {angle_deg}° OK",
        theta=angle_deg,
        swaths=len(all_swaths),
        C_max=round(max(r.T_total_s for r in all_routes), 1),
    )

    return _build_candidate(
        theta_deg=angle_deg,
        all_routes=all_routes,
        decomposition_method=mission.params.decomposition,
    )


# ============================================================
# Выбор лучшего
# ============================================================

def select_best(candidates: list[Candidate], criterion: Criterion) -> Candidate:
    if not candidates:
        raise ValueError("No candidates")
    key = (
        (lambda c: c.C_max_s)
        if criterion == Criterion.MIN_TIME
        else (lambda c: c.flight_hours_s)
    )
    return min(candidates, key=key)


def _candidate_metric(c: Candidate, criterion: Criterion) -> float:
    return c.C_max_s if criterion == Criterion.MIN_TIME else c.flight_hours_s


# ============================================================
# Применение overrides к mission
# ============================================================

def _apply_overrides(
    mission: MissionInput,
    criterion_override: Criterion | str | None,
    angle_override: float | None,
) -> MissionInput:
    """Возвращает копию mission с применёнными overrides."""
    updates: dict = {}

    if angle_override is not None:
        updates["angles_deg"] = [float(angle_override)]

    if criterion_override is not None:
        crit = (
            criterion_override
            if isinstance(criterion_override, Criterion)
            else Criterion(criterion_override)
        )
        updates["optimization_criterion"] = crit

    if not updates:
        return mission

    new_params = mission.params.model_copy(update=updates)
    return mission.model_copy(update={"params": new_params})


# ============================================================
# Выбор углов для перебора
# ============================================================

def _angles_to_try(mission: MissionInput) -> list[float]:
    """Список углов для перебора.

    Для fields2cover — один угол (0.0): F2C сам выбирает направление.
    НО: если F2C импортируется, но падает на реальной геометрии
    (например, после difference от obstacles), заранее проверяем его
    на первой области. Если проба падает — полный перебор.

    Для trapezoid / triangulation / auto — полный список из params.
    """
    decomp = mission.params.decomposition
    if decomp != DecompositionMethod.FIELDS2COVER:
        return list(mission.params.angles_deg)

    from planner.geometry.f2c_backend import (
        is_available as f2c_available,
        generate_swaths_f2c,
    )
    if not f2c_available():
        log_warn(
            "pipeline",
            "decomposition=fields2cover, но F2C недоступен — "
            "полный перебор углов",
        )
        return list(mission.params.angles_deg)

    if not mission.areas:
        return [0.0]

    # Пробный вызов F2C на первой области
    try:
        from shapely.geometry import Polygon, shape
        from planner.utils.geo import make_local_transformer

        area = mission.areas[0]
        poly_wgs = shape(area.polygon)
        c = poly_wgs.centroid
        fwd, _ = make_local_transformer(c.x, c.y)

        coords_m = [
            fwd.transform(x, y) for x, y in poly_wgs.exterior.coords
        ]
        poly_m = Polygon(coords_m)

        probe = generate_swaths_f2c(poly_m, 20.0)
        if probe:
            log_info(
                "pipeline",
                f"F2C рабочий (проба: {len(probe)} полос) — "
                f"один угол 0.0",
            )
            return [0.0]
        log_warn(
            "pipeline",
            "F2C дал 0 полос на пробе — полный перебор углов",
        )
        return list(mission.params.angles_deg)

    except Exception as e:
        log_warn(
            "pipeline",
            f"F2C упал на пробе ({type(e).__name__}: {e}) — "
            f"полный перебор углов",
        )
        return list(mission.params.angles_deg)


# ============================================================
# Полный прогон
# ============================================================

def run_mission(
    fixtures_dir: str | Path,
    output_dir: str | Path,
    criterion_override: Criterion | str | None = None,
    angle_override: float | None = None,
) -> Report:
    """Полный прогон миссии."""
    mission = load_mission(fixtures_dir)
    mission = _apply_overrides(
        mission,
        criterion_override=criterion_override,
        angle_override=angle_override,
    )

    catalog = get_default_catalog()
    counters = Counters()
    candidates: list[Candidate] = []

    swaths_by_theta: dict[float, dict[str, Swath]] = {}

    max_takeoff_mass_kg: float | None = None
    for uav in mission.uavs:
        m = _max_takeoff_mass_kg(catalog, uav.model)
        if m is not None:
            max_takeoff_mass_kg = (
                m if max_takeoff_mass_kg is None
                else max(max_takeoff_mass_kg, m)
            )

    criterion = mission.params.optimization_criterion
    patience = mission.params.angles_early_stop_patience
    patience_left = patience
    best_metric: float | None = None
    n_angles_tried = 0

    angles = _angles_to_try(mission)

    for theta in angles:
        counters.reset_attempts()
        swaths_by_area, h_agl_by_area = _generate_all_swaths(mission, theta)
        swaths_by_theta[theta] = {
            s.id: s for sw in swaths_by_area.values() for s in sw
        }
        n_angles_tried += 1

        cand = run_one_angle(
            mission=mission,
            angle_deg=theta,
            counters=counters,
            swaths_by_area=swaths_by_area,
            h_agl_by_area=h_agl_by_area,
            max_takeoff_mass_kg=max_takeoff_mass_kg,
        )
        if cand is not None:
            candidates.append(cand)

        # Early stop — только если углов больше одного
        if patience > 0 and len(angles) > 1:
            if cand is None:
                if best_metric is not None:
                    patience_left -= 1
                    if patience_left <= 0:
                        log_info(
                            "pipeline",
                            f"early stop at theta={theta}° (no candidate)",
                        )
                        break
            else:
                metric = _candidate_metric(cand, criterion)
                if best_metric is None or metric < best_metric:
                    best_metric = metric
                    patience_left = patience
                else:
                    patience_left -= 1
                    if patience_left <= 0:
                        log_info(
                            "pipeline",
                            f"early stop at theta={theta}° "
                            f"(no improvement, best={best_metric:.1f})",
                        )
                        break

    if not candidates:
        raise RuntimeError("No valid candidates found")

    best = select_best(candidates, criterion)

    best_swaths_by_id: dict[str, Swath] = swaths_by_theta.get(
        best.theta_deg, {}
    )

    per_uav: dict[str, UAVSummary] = {}
    for r in best.routes:
        if r.uav_id not in per_uav:
            per_uav[r.uav_id] = UAVSummary(
                uav_id=r.uav_id, n_flights=0,
                T_air_s=0.0, T_total_s=0.0, E_wh=0.0,
                mass_kg=r.mass_kg, T_charge_s=r.T_charge_s,
            )
        s = per_uav[r.uav_id]
        s.n_flights += 1
        s.T_air_s += r.T_air_s
        s.T_total_s += r.T_total_s
        s.E_wh += r.E_wh

    for s in per_uav.values():
        s.T_mission_s = s.T_total_s + max(0, s.n_flights - 1) * s.T_charge_s

    n_photos_total = sum(
        best_swaths_by_id[sid].n_photos
        for r in best.routes
        for sid in r.swath_ids
        if sid in best_swaths_by_id
    )

    metrics = Metrics(
        C_max_s=best.C_max_s,
        flight_hours_total_s=best.flight_hours_s,
        energy_total_wh=best.energy_total_wh,
        n_uavs_used=best.n_uavs_used,
        n_swaths_total=sum(len(r.swath_ids) for r in best.routes),
        n_photos_total=n_photos_total,
    )

    report = Report(
        mission_id="mvp",
        theta_best_deg=best.theta_deg,
        decomposition_method=best.decomposition_method,
        optimization_criterion=mission.params.optimization_criterion,
        metrics=metrics,
        per_uav=list(per_uav.values()),
        n_angles_tried=n_angles_tried,
        n_candidates=len(candidates),
    )

    from planner.io.json_out import write_report_json
    from planner.io.kml_out import write_routes_kml

    out = Path(output_dir) / "mission"
    out.mkdir(parents=True, exist_ok=True)

    write_report_json(out / "report.json", report)
    write_routes_kml(
        out / "routes.kml",
        mission=mission,
        candidate=best,
        swaths_by_id=best_swaths_by_id,
    )

    return report