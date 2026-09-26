"""Валидатор: покрытие, время, энергия, масса, рельеф, препятствия."""

from __future__ import annotations

from dataclasses import dataclass, field

from planner.models import MissionInput, Obstacle, Route, Swath
from planner.physics.base import PhysicsParams


@dataclass
class CheckResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ============================================================
# Покрытие
# ============================================================

def check_coverage(
    all_swaths: list[Swath],
    routes: list[Route],
) -> list[str]:
    errors: list[str] = []

    covered: list[str] = []
    for r in routes:
        covered.extend(r.swath_ids)

    seen: dict[str, int] = {}
    for sid in covered:
        seen[sid] = seen.get(sid, 0) + 1

    all_ids = {s.id for s in all_swaths}
    covered_ids = set(covered)
    missing = all_ids - covered_ids
    if missing:
        errors.append(f"Swaths not covered: {sorted(missing)}")

    dupes = [sid for sid, cnt in seen.items() if cnt > 1]
    if dupes:
        errors.append(f"Swaths covered more than once: {sorted(dupes)}")

    return errors


# ============================================================
# Время / энергия
# ============================================================

def check_time_energy(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
) -> list[str]:
    errors: list[str] = []

    for r in routes:
        p = params_by_uav.get(r.uav_id)
        if p is None:
            errors.append(f"No physics params for uav {r.uav_id}")
            continue

        T_limit = p.T_max_s * (1.0 - p.reserve_fraction)
        E_limit = p.E_batt_wh * (1.0 - p.reserve_fraction)

        if r.T_total_s > T_limit + 1e-3:
            errors.append(
                f"UAV {r.uav_id} flight {r.flight_index}: "
                f"T_total={r.T_total_s:.1f}s > limit {T_limit:.1f}s"
            )
        if r.E_wh > E_limit + 1e-3:
            errors.append(
                f"UAV {r.uav_id} flight {r.flight_index}: "
                f"E={r.E_wh:.2f}Wh > limit {E_limit:.2f}Wh"
            )

    return errors


# ============================================================
# Масса
# ============================================================

def check_mass(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    max_takeoff_mass_kg: float | None = None,
) -> list[str]:
    errors: list[str] = []
    if max_takeoff_mass_kg is None:
        return errors

    for r in routes:
        p = params_by_uav.get(r.uav_id)
        if p is None:
            continue
        if p.mass_kg > max_takeoff_mass_kg + 1e-6:
            errors.append(
                f"UAV {r.uav_id}: mass {p.mass_kg}kg > max {max_takeoff_mass_kg}kg"
            )
    return errors


# ============================================================
# Рельеф — безопасность полос
# ============================================================

def check_terrain_safety(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    safety_margin_m: float,
) -> list[str]:
    errors: list[str] = []

    if safety_margin_m <= 0:
        return errors

    for r in routes:
        for sid in r.swath_ids:
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            h_min = s.h_agl_min_m if s.h_agl_min_m > 0 else s.h_agl_m
            if h_min < safety_margin_m - 1e-3:
                errors.append(
                    f"Swath {sid}: min h_agl={h_min:.1f}m < "
                    f"safety_margin={safety_margin_m:.1f}m"
                )

    return errors


# ============================================================
# Рельеф — физическая выполнимость
# ============================================================

def check_terrain_feasibility(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
) -> list[str]:
    errors: list[str] = []
    for r in routes:
        for sid in r.swath_ids:
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            if not s.feasible:
                errors.append(
                    f"Swath {sid} infeasible: {s.infeasible_reason}"
                )
    return errors


# ============================================================
# Рельеф — безопасность на перелётах
# ============================================================

def check_route_terrain_safety(
    routes: list[Route],
    dem,
    safety_margin_m: float,
) -> list[str]:
    errors: list[str] = []
    if dem is None or safety_margin_m <= 0:
        return errors

    try:
        if dem.is_empty():
            return errors
    except AttributeError:
        return errors

    for r in routes:
        if not getattr(r, "waypoints", None):
            continue
        for i, wp in enumerate(r.waypoints):
            dem_h = dem.h(wp.lat, wp.lon)
            h_agl = wp.alt_m - dem_h
            if h_agl < safety_margin_m - 1e-3:
                errors.append(
                    f"UAV {r.uav_id} flight {r.flight_index} "
                    f"waypoint {i}: h_agl={h_agl:.1f}m < "
                    f"safety={safety_margin_m:.1f}m"
                )
    return errors


# ============================================================
# Препятствия — вертикальный зазор над ними
# ============================================================

def check_obstacle_clearance(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    obstacles: list[Obstacle],
    dem,
    safety_margin_obstacle_m: float,
) -> list[str]:
    """
    Проверяет вертикальный зазор над препятствиями:
    h_asl - (DEM + obstacle.height) >= safety_margin_obstacle_m
    для всех точек маршрута, лежащих над footprint препятствия.
    """
    errors: list[str] = []
    if safety_margin_obstacle_m <= 0 or not obstacles:
        return errors

    from shapely.geometry import Point as ShPoint, shape

    obs_geoms = []
    for obs in obstacles:
        try:
            geom = shape(obs.polygon)
        except Exception:
            continue
        obs_geoms.append((obs.id, obs.height_m, geom))

    if not obs_geoms:
        return errors

    def dem_h(lat: float, lon: float) -> float:
        if dem is None:
            return 0.0
        try:
            if dem.is_empty():
                return 0.0
        except AttributeError:
            return 0.0
        return dem.h(lat, lon)

    for r in routes:
        # 1. Сегменты полос
        for sid in r.swath_ids:
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            for seg in s.segments:
                pt = ShPoint(seg.lon, seg.lat)
                for obs_id, obs_h, obs_geom in obs_geoms:
                    if obs_geom.covers(pt):
                        top = dem_h(seg.lat, seg.lon) + obs_h
                        h_above = seg.h_asl_m - top
                        if h_above < safety_margin_obstacle_m - 1e-3:
                            errors.append(
                                f"Swath {sid} over {obs_id}: "
                                f"clearance={h_above:.1f}m < "
                                f"{safety_margin_obstacle_m:.1f}m"
                            )
                        break

        # 2. Waypoints на перелётах
        for i, wp in enumerate(getattr(r, "waypoints", []) or []):
            pt = ShPoint(wp.lon, wp.lat)
            for obs_id, obs_h, obs_geom in obs_geoms:
                if obs_geom.covers(pt):
                    top = dem_h(wp.lat, wp.lon) + obs_h
                    h_above = wp.alt_m - top
                    if h_above < safety_margin_obstacle_m - 1e-3:
                        errors.append(
                            f"UAV {r.uav_id} flight {r.flight_index} "
                            f"wp {i} over {obs_id}: "
                            f"clearance={h_above:.1f}m < "
                            f"{safety_margin_obstacle_m:.1f}m"
                        )
                    break

    return errors


# ============================================================
# Препятствия — 2D пересечение полос
# ============================================================

def check_obstacles(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    obstacles_polygons: list,
) -> list[str]:
    from shapely.geometry import LineString, shape

    errors: list[str] = []
    obs_geoms = [shape(o) for o in obstacles_polygons]

    for r in routes:
        for sid in r.swath_ids:
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            line = LineString([
                (s.start.lon, s.start.lat),
                (s.end.lon, s.end.lat),
            ])
            for obs in obs_geoms:
                if line.intersects(obs):
                    errors.append(f"Swath {sid} intersects obstacle")
                    break

    return errors


# ============================================================
# Полная валидация
# ============================================================

def validate(
    mission: MissionInput,
    all_swaths: list[Swath],
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    max_takeoff_mass_kg: float | None = None,
) -> CheckResult:
    errors: list[str] = []

    # 1. Покрытие
    errors.extend(check_coverage(all_swaths, routes))

    # 2. Время и энергия
    errors.extend(check_time_energy(routes, params_by_uav))

    # 3. Масса
    errors.extend(check_mass(routes, params_by_uav, max_takeoff_mass_kg))

    swaths_by_id = {s.id: s for s in all_swaths}

    # 4. Рельеф — безопасность полос
    if mission.params.safety_margin_m > 0:
        errors.extend(
            check_terrain_safety(
                routes, swaths_by_id, mission.params.safety_margin_m
            )
        )

    # 5. Рельеф — физическая выполнимость
    errors.extend(check_terrain_feasibility(routes, swaths_by_id))

    # 6. Рельеф — безопасность на перелётах
    if mission.dem is not None:
        errors.extend(
            check_route_terrain_safety(
                routes, mission.dem, mission.params.safety_margin_m
            )
        )

    # 7. NEW: Препятствия — вертикальный зазор над ними
    if mission.obstacles and mission.params.safety_margin_obstacle_m > 0:
        errors.extend(
            check_obstacle_clearance(
                routes=routes,
                swaths_by_id=swaths_by_id,
                obstacles=mission.obstacles,
                dem=mission.dem,
                safety_margin_obstacle_m=mission.params.safety_margin_obstacle_m,
            )
        )

    # 8. Препятствия — 2D пересечение
    obstacles_polys = [o.polygon for o in mission.obstacles]
    if obstacles_polys:
        errors.extend(check_obstacles(routes, swaths_by_id, obstacles_polys))

    return CheckResult(valid=len(errors) == 0, errors=errors)