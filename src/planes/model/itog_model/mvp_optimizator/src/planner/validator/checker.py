"""Валидатор: покрытие, время, энергия, масса, рельеф, препятствия, ветер."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from planner.models import MissionInput, Obstacle, Route, Swath
from planner.physics.base import PhysicsParams
from planner.utils.route_metrics import bearing_deg as route_bearing_deg
from planner.utils.route_metrics import haversine_m
from planner.utils.wind import ground_speed_mps as wind_ground_speed_mps


CHECK_STEP_M = 30.0


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
    max_takeoff_mass_kg: float | None,
) -> list[str]:
    errors: list[str] = []
    if max_takeoff_mass_kg is None:
        return errors

    seen_uavs: set[str] = set()
    for r in routes:
        if r.uav_id in seen_uavs:
            continue
        p = params_by_uav.get(r.uav_id)
        if p is None:
            continue
        seen_uavs.add(r.uav_id)
        if p.mass_kg > max_takeoff_mass_kg + 1e-6:
            errors.append(
                f"UAV {r.uav_id}: mass {p.mass_kg}kg > "
                f"max {max_takeoff_mass_kg}kg"
            )
    return errors


# ============================================================
# Рельеф — безопасность полос
# ============================================================

def _swath_min_agl(s: Swath) -> float:
    if s.h_agl_min_m is not None:
        return s.h_agl_min_m
    return s.h_agl_m


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
            h_min = _swath_min_agl(s)
            if h_min < safety_margin_m - 1e-3:
                errors.append(
                    f"Swath {sid}: min h_agl={h_min:.1f}m < "
                    f"safety_margin={safety_margin_m:.1f}m"
                )

    return errors


# ============================================================
# Рельеф — физическая выполнимость (warnings, не errors)
# ============================================================

def check_terrain_feasibility(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
) -> tuple[list[str], list[str]]:
    """Проверяет feasible полос.

    Возвращает (errors, warnings).
    Errors пусты: infeasible полосы — не критическая ошибка (кандидат
    уже получает штраф по времени/энергии в generate). Это предупреждение.
    """
    warnings: list[str] = []
    seen: set[str] = set()

    for r in routes:
        for sid in r.swath_ids:
            if sid in seen:
                continue
            seen.add(sid)
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            if not s.feasible:
                warnings.append(
                    f"Swath {sid} infeasible (penalty applied): "
                    f"{s.infeasible_reason}"
                )

    return [], warnings


# ============================================================
# Рельеф — безопасность на перелётах (только waypoints)
# ============================================================

def check_route_terrain_safety(
    routes: list[Route],
    dem,
    safety_margin_m: float,
) -> list[str]:
    """Проверяет AGL **только в waypoints** маршрута.

    Это фактическая проверка: waypoints — это точки, через которые
    борт точно пролетает. Если хоть одна ниже safety — ошибка.

    Интерполяция между waypoints — отдельная функция
    check_route_terrain_safety_interpolated().
    """
    errors: list[str] = []
    if dem is None or safety_margin_m <= 0:
        return errors

    try:
        if dem.is_empty():
            return errors
    except AttributeError:
        return errors

    for r in routes:
        wps = getattr(r, "waypoints", None) or []
        for i, wp in enumerate(wps):
            dem_h = dem.h(wp.lat, wp.lon)
            h_agl = wp.alt_m - dem_h
            if h_agl < safety_margin_m - 1e-3:
                errors.append(
                    f"UAV {r.uav_id} flight {r.flight_index} "
                    f"waypoint {i} ({wp.lat:.5f},{wp.lon:.5f}): "
                    f"h_agl={h_agl:.1f}m < safety={safety_margin_m:.1f}m"
                )
    return errors


# ============================================================
# Рельеф — безопасность между waypoints (интерполяция)
# ============================================================

def _interpolate_waypoints(
    wps: list,
    step_m: float = CHECK_STEP_M,
) -> list[tuple[float, float, float]]:
    """Разбивает waypoints на точки с шагом ~step_m.

    Возвращает (lat, lon, alt_m). Высота между waypoints
    интерполируется линейно — это worst-case оценка.
    """
    if len(wps) < 2:
        return [(wp.lat, wp.lon, wp.alt_m) for wp in wps]

    out: list[tuple[float, float, float]] = [
        (wps[0].lat, wps[0].lon, wps[0].alt_m)
    ]
    for i in range(len(wps) - 1):
        p1 = wps[i]
        p2 = wps[i + 1]
        d = haversine_m(p1, p2)
        if d < step_m:
            out.append((p2.lat, p2.lon, p2.alt_m))
            continue
        n = int(np.ceil(d / step_m))
        for k in range(1, n + 1):
            t = k / n
            lat = p1.lat + (p2.lat - p1.lat) * t
            lon = p1.lon + (p2.lon - p1.lon) * t
            alt = p1.alt_m + (p2.alt_m - p1.alt_m) * t
            out.append((lat, lon, alt))

    return out


def check_route_terrain_safety_interpolated(
    routes: list[Route],
    dem,
    safety_margin_m: float,
    step_m: float = CHECK_STEP_M,
    max_violations: int = 5,
) -> list[str]:
    """Проверяет AGL **между waypoints** с линейной интерполяцией.

    Возвращает список нарушений (максимум max_violations на маршрут).
    Используется как warning по умолчанию: линейная интерполяция
    даёт ложные срабатывания на пиках DEM между waypoints.

    Если нужно — вызывающий код может превратить это в errors
    (см. validate(..., strict_terrain_check=True)).
    """
    warnings: list[str] = []
    if dem is None or safety_margin_m <= 0:
        return warnings

    try:
        if dem.is_empty():
            return warnings
    except AttributeError:
        return warnings

    for r in routes:
        wps = getattr(r, "waypoints", None) or []
        if len(wps) < 2:
            continue

        samples = _interpolate_waypoints(wps, step_m)
        violations = 0
        for i, (lat, lon, alt) in enumerate(samples):
            dem_h = dem.h(lat, lon)
            h_agl = alt - dem_h
            if h_agl < safety_margin_m - 1e-3:
                warnings.append(
                    f"UAV {r.uav_id} flight {r.flight_index} "
                    f"sample {i} ({lat:.5f},{lon:.5f}): "
                    f"h_agl={h_agl:.1f}m < safety={safety_margin_m:.1f}m"
                )
                violations += 1
                if violations >= max_violations:
                    warnings.append(
                        f"UAV {r.uav_id} flight {r.flight_index}: "
                        f"... более {max_violations} нарушений, "
                        f"список обрезан"
                    )
                    break

    return warnings


# ============================================================
# Рельеф — сводка
# ============================================================

def check_terrain_safety_summary(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    safety_margin_m: float,
) -> list[str]:
    """Информационная сводка по terrain safety.

    'Terrain summary: safe=X/N, borderline=Y, infeasible=Z'
    Возвращает [] если все safe (Y=0 и Z=0).
    """
    if safety_margin_m <= 0:
        return []

    safe = 0
    borderline = 0
    infeasible = 0
    seen: set[str] = set()

    for r in routes:
        for sid in r.swath_ids:
            if sid in seen:
                continue
            seen.add(sid)
            s = swaths_by_id.get(sid)
            if s is None:
                continue
            if not s.feasible:
                infeasible += 1
                continue
            h_min = _swath_min_agl(s)
            if h_min >= safety_margin_m:
                safe += 1
            elif h_min >= 0.8 * safety_margin_m:
                borderline += 1
            else:
                infeasible += 1

    total = safe + borderline + infeasible
    if total == 0:
        return []

    # Не шумим, если всё чисто
    if borderline == 0 and infeasible == 0:
        return []

    return [
        f"Terrain summary: safe={safe}/{total}, "
        f"borderline={borderline}, infeasible={infeasible}"
    ]


# ============================================================
# Ветер — выполнимость для fixed-wing
# ============================================================

def check_wind_feasibility(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    wind_speed_mps: float,
    wind_direction_deg: float,
) -> list[str]:
    errors: list[str] = []
    if wind_speed_mps <= 0:
        return errors

    for r in routes:
        p = params_by_uav.get(r.uav_id)
        if p is None or p.v_stall_mps <= 0:
            continue

        wps = getattr(r, "waypoints", None) or []
        if len(wps) < 2:
            continue

        for i in range(len(wps) - 1):
            p1 = wps[i]
            p2 = wps[i + 1]

            d = haversine_m(p1, p2)
            if d < 1e-6:
                continue

            br = route_bearing_deg(p1, p2)
            v_g = wind_ground_speed_mps(
                p.v_air_mps, br, wind_speed_mps, wind_direction_deg
            )

            if v_g < p.v_stall_mps - 1e-3:
                errors.append(
                    f"UAV {r.uav_id} flight {r.flight_index} leg {i}: "
                    f"v_ground={v_g:.1f} m/s < v_stall={p.v_stall_mps:.1f} "
                    f"m/s (bearing={br:.0f}°, wind={wind_speed_mps:.1f} "
                    f"m/s @ {wind_direction_deg:.0f}°)"
                )
                break

    return errors


# ============================================================
# Препятствия — вертикальный зазор
# ============================================================

def check_obstacle_clearance(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    obstacles: list[Obstacle],
    dem,
    safety_margin_obstacle_m: float,
) -> list[str]:
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
# Препятствия — 2D пересечение сегментов
# ============================================================

def _swath_line_coords(s: Swath) -> list[tuple[float, float]]:
    if s.segments and len(s.segments) >= 2:
        return [(seg.lon, seg.lat) for seg in s.segments]
    return [(s.start.lon, s.start.lat), (s.end.lon, s.end.lat)]


def _segment_intersects(seg, obs, min_length_m: float = 0.5) -> bool:
    inter = seg.intersection(obs)
    if inter.is_empty:
        return False

    gt = inter.geom_type
    if gt == "LineString":
        return inter.length > min_length_m
    if gt == "MultiLineString":
        return sum(g.length for g in inter.geoms) > min_length_m
    if gt == "GeometryCollection":
        total = 0.0
        for g in inter.geoms:
            if g.geom_type == "LineString":
                total += g.length
            elif g.geom_type == "MultiLineString":
                total += sum(x.length for x in g.geoms)
        return total > min_length_m
    return False


def check_obstacles(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    obstacles_polygons: list,
) -> list[str]:
    from shapely.geometry import LineString, shape

    errors: list[str] = []
    obs_geoms = [shape(o) for o in obstacles_polygons]
    if not obs_geoms:
        return errors

    for r in routes:
        for sid in r.swath_ids:
            s = swaths_by_id.get(sid)
            if s is None:
                continue

            coords = _swath_line_coords(s)
            if len(coords) < 2:
                continue

            hit = False
            for k in range(len(coords) - 1):
                line = LineString([coords[k], coords[k + 1]])
                for obs in obs_geoms:
                    if _segment_intersects(line, obs):
                        errors.append(
                            f"Swath {sid} segment {k} intersects obstacle"
                        )
                        hit = True
                        break
                if hit:
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
    strict_terrain_check: bool = False,
) -> CheckResult:
    """Полная валидация миссии.

    Args:
        strict_terrain_check: если True — нарушения terrain safety
            между waypoints (по интерполяции) становятся errors,
            а не warnings. По умолчанию False — эти нарушения
            не отбрасывают кандидат, а идут в отчёт как предупреждения.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 0. Наличие физики
    missing_uavs = sorted({
        r.uav_id for r in routes if r.uav_id not in params_by_uav
    })
    if missing_uavs:
        errors.append(f"No physics params for uavs: {missing_uavs}")

    # 1. Покрытие
    errors.extend(check_coverage(all_swaths, routes))

    # 2. Время и энергия
    errors.extend(check_time_energy(routes, params_by_uav))

    # 3. Масса
    if max_takeoff_mass_kg is not None:
        errors.extend(check_mass(routes, params_by_uav, max_takeoff_mass_kg))
    else:
        warnings.append("Mass check disabled: max_takeoff_mass_kg is None")

    swaths_by_id = {s.id: s for s in all_swaths}

    # 4. Рельеф — безопасность полос
    if mission.params.safety_margin_m > 0:
        errors.extend(
            check_terrain_safety(
                routes, swaths_by_id, mission.params.safety_margin_m
            )
        )

    # 5. Рельеф — физическая выполнимость (warnings)
    feas_errors, feas_warnings = check_terrain_feasibility(
        routes, swaths_by_id
    )
    errors.extend(feas_errors)
    warnings.extend(feas_warnings)

    # 5b. Рельеф — сводка
    warnings.extend(
        check_terrain_safety_summary(
            routes, swaths_by_id, mission.params.safety_margin_m
        )
    )

    # 6. Рельеф — безопасность на waypoints (errors)
    if mission.dem is not None:
        errors.extend(
            check_route_terrain_safety(
                routes, mission.dem, mission.params.safety_margin_m
            )
        )

    # 6b. Рельеф — безопасность между waypoints (warnings или errors)
    if mission.dem is not None:
        interp = check_route_terrain_safety_interpolated(
            routes, mission.dem, mission.params.safety_margin_m
        )
        if strict_terrain_check:
            errors.extend(interp)
        else:
            warnings.extend(interp)

    # 7. Ветер — выполнимость для fixed-wing
    errors.extend(
        check_wind_feasibility(
            routes=routes,
            params_by_uav=params_by_uav,
            wind_speed_mps=mission.params.wind.speed_mps,
            wind_direction_deg=mission.params.wind.direction_deg,
        )
    )

    # 8. Препятствия — вертикальный зазор
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

    # 9. Препятствия — 2D пересечение
    obstacles_polys = [o.polygon for o in mission.obstacles]
    if obstacles_polys:
        errors.extend(check_obstacles(routes, swaths_by_id, obstacles_polys))

    return CheckResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )