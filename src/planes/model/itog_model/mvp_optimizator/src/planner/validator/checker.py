"""Валидатор: покрытие, ограничения времени/энергии/массы."""

from __future__ import annotations

from dataclasses import dataclass, field

from planner.models import MissionInput, Route, Swath
from planner.physics.base import PhysicsParams


@dataclass
class CheckResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_coverage(
    all_swaths: list[Swath],
    routes: list[Route],
) -> list[str]:
    """Все полосы сняты ровно один раз."""
    errors: list[str] = []

    covered: list[str] = []
    for r in routes:
        covered.extend(r.swath_ids)

    seen: dict[str, int] = {}
    for sid in covered:
        seen[sid] = seen.get(sid, 0) + 1

    # Пропущенные
    all_ids = {s.id for s in all_swaths}
    covered_ids = set(covered)
    missing = all_ids - covered_ids
    if missing:
        errors.append(f"Swaths not covered: {sorted(missing)}")

    # Дубликаты
    dupes = [sid for sid, cnt in seen.items() if cnt > 1]
    if dupes:
        errors.append(f"Swaths covered more than once: {sorted(dupes)}")

    return errors


def check_time_energy(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
) -> list[str]:
    """T_total ≤ T_max·(1−reserve) и E ≤ E_batt·(1−reserve) на каждый вылет."""
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


def check_mass(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    max_takeoff_mass_kg: float | None = None,
) -> list[str]:
    """Масса с нагрузкой ≤ max_takeoff (если задано)."""
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


def check_obstacles(
    routes: list[Route],
    swaths_by_id: dict[str, Swath],
    obstacles_polygons: list,
) -> list[str]:
    """
    Простая проверка: полоса не пересекает footprint препятствия.
    На MVP полосы генерируются уже с вычетом препятствий,
    но проверяем на всякий случай.
    """
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


def validate(
    mission: MissionInput,
    all_swaths: list[Swath],
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    max_takeoff_mass_kg: float | None = None,
) -> CheckResult:
    """Полная проверка решения."""
    errors: list[str] = []

    errors.extend(check_coverage(all_swaths, routes))
    errors.extend(check_time_energy(routes, params_by_uav))
    errors.extend(check_mass(routes, params_by_uav, max_takeoff_mass_kg))

    # Препятствия — опционально
    swaths_by_id = {s.id: s for s in all_swaths}
    obstacles_polys = [o.polygon for o in mission.obstacles]
    if obstacles_polys:
        errors.extend(check_obstacles(routes, swaths_by_id, obstacles_polys))

    return CheckResult(valid=len(errors) == 0, errors=errors)