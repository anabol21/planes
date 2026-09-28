"""Пересчёт метрик маршрута из реальных waypoints.

Метрики считаются по каждой паре точек:
    d  = haversine(p1, p2)
    br = bearing(p1, p2)
    v_g = ground_speed(v_air, br, wind)
    t  = d / v_g
    e  = P·t/3600 + m·g·max(dh, 0)/3600

Используется в pipeline для пересчёта T_air_s, E_air_wh после
построения waypoints (terrain corridor + B-spline).

recalc_all_routes() сохраняет разницу между воздушной и полной
энергией (E_to + E_ld), чтобы не терять её при пересчёте.
"""

from __future__ import annotations

import math

from planner.models import Point, Route
from planner.physics.base import PhysicsParams
from planner.utils.wind import ground_speed_mps


G = 9.81
R_EARTH_M = 6371000.0


# ============================================================
# Геометрия
# ============================================================

def haversine_m(p1: Point, p2: Point) -> float:
    """Расстояние по поверхности Земли, метры."""
    lat1 = math.radians(p1.lat)
    lat2 = math.radians(p2.lat)
    dlat = math.radians(p2.lat - p1.lat)
    dlon = math.radians(p2.lon - p1.lon)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * R_EARTH_M * math.asin(math.sqrt(a))


def bearing_deg(p1: Point, p2: Point) -> float:
    """Курс из p1 в p2 (0 = север, 90 = восток)."""
    lat1 = math.radians(p1.lat)
    lat2 = math.radians(p2.lat)
    dlon = math.radians(p2.lon - p1.lon)

    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )
    return math.degrees(math.atan2(x, y)) % 360.0


# ============================================================
# Пересчёт одного маршрута
# ============================================================

def recalc_route_metrics(
    route: Route,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
    P_nominal_w: float,
) -> tuple[float, float]:
    """Пересчитывает (T_air_s, E_air_wh) из реальных waypoints.

    Возвращает (T_air_s, E_air_wh) — только воздушную часть
    (перелёты между waypoints + набор высоты). Взлёт/посадка
    сюда не входят.
    """
    if not route.waypoints or len(route.waypoints) < 2:
        return route.T_air_s, route.E_air_wh

    T_total = 0.0
    E_total = 0.0

    for i in range(len(route.waypoints) - 1):
        p1 = route.waypoints[i]
        p2 = route.waypoints[i + 1]

        d = haversine_m(p1, p2)
        if d < 1e-6:
            continue

        dh = p2.alt_m - p1.alt_m
        br = bearing_deg(p1, p2)

        v_g = ground_speed_mps(
            params.v_air_mps, br, wind_speed_mps, wind_direction_deg
        )
        t_seg = d / v_g

        P = P_nominal_w
        if dh > 0:
            P += params.mass_kg * G * dh / max(t_seg, 0.1)

        e_seg = P * t_seg / 3600.0

        T_total += t_seg
        E_total += e_seg

    return T_total, E_total


# ============================================================
# Пересчёт всех маршрутов
# ============================================================

def recalc_all_routes(
    routes: list[Route],
    params_by_uav: dict[str, PhysicsParams],
    wind_speed_mps: float,
    wind_direction_deg: float,
    P_nominal_by_uav: dict[str, float],
) -> None:
    """Пересчитывает метрики всех маршрутов in-place.

    Сохраняет разницу между полной и воздушной частью:
        delta_T = T_total_s − T_air_s = T_to + T_ld
        delta_E = E_wh − E_air_wh = E_to + E_ld

    После пересчёта:
        T_air_s  = T_new
        E_air_wh = E_new
        T_total_s = T_new + delta_T
        E_wh      = E_new + delta_E

    Инвариант:
        E_wh = E_air_wh + E_to + E_ld
    """
    for r in routes:
        pp = params_by_uav.get(r.uav_id)
        if pp is None:
            continue
        P_nom = P_nominal_by_uav.get(r.uav_id, 300.0)

        # --- Сохраняем разницу до пересчёта ---
        delta_T = max(r.T_total_s - r.T_air_s, 0.0)

        # delta_E = E_to + E_ld. Если E_air_wh не заполнено (>0),
        # считаем delta_E = 0 (legacy / fixed-wing: E_to = E_ld = 0).
        if r.E_air_wh > 0.0:
            delta_E = max(r.E_wh - r.E_air_wh, 0.0)
        else:
            delta_E = 0.0

        # --- Пересчёт воздушной части ---
        T_new, E_new = recalc_route_metrics(
            route=r,
            params=pp,
            wind_speed_mps=wind_speed_mps,
            wind_direction_deg=wind_direction_deg,
            P_nominal_w=P_nom,
        )

        r.T_air_s = T_new
        r.E_air_wh = E_new
        r.T_total_s = T_new + delta_T
        r.E_wh = E_new + delta_E