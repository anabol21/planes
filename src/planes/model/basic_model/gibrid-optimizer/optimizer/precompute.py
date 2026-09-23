"""Предвычисления: матрицы расстояний, времён, энергий, взлёт/посадка."""

from math import radians, degrees, sin, cos, atan2, sqrt
from typing import Any, Dict, List

import numpy as np

from .models import InputData
from .geometry import Strip


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Расстояние по большому кругу, м."""
    R = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Начальный азимут из точки 1 в точку 2, °."""
    p1, p2 = radians(lat1), radians(lat2)
    dl = radians(lon2 - lon1)
    x = sin(dl) * cos(p2)
    y = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return (degrees(atan2(x, y)) + 360.0) % 360.0


def ground_speed(v_air, bearing, wind_speed, wind_from_dir) -> float:
    """Путевая скорость при полёте с воздушной скоростью v_air по курсу
    bearing при ветре, дующем ОТ направления wind_from_dir.
    """
    b = radians(bearing)
    vax = v_air * sin(b)
    vay = v_air * cos(b)
    wd = radians(wind_from_dir + 180.0)
    wx = wind_speed * sin(wd)
    wy = wind_speed * cos(wd)
    return sqrt((vax + wx) ** 2 + (vay + wy) ** 2)


def power_w(mass_kg, v_ms, wind_ms, kh, kv, kw) -> float:
    """Мощность по формуле из milp.pdf: P = kh·m + kv·v³ + kw·|w|²·m."""
    return kh * mass_kg + kv * (v_ms ** 3) + kw * (wind_ms ** 2) * mass_kg


def precompute(
    input_data: InputData,
    strips: List[Strip],
    altitude_m: float,
) -> Dict[str, Any]:
    """Строит все предвычисленные величины для оптимизатора.

    Возвращаемый словарь — общий контракт для обоих решателей.
    """
    uav = input_data.uav
    wind = input_data.wind
    coeffs = input_data.power_coeffs
    turn_time = input_data.solver.turn_time_s
    apply_turn_to_base = input_data.solver.apply_turn_to_base

    M = len(strips)
    N = M + 1

    base = (input_data.takeoff.lat, input_data.takeoff.lon)
    entries = [base] + [s[0] for s in strips]
    exits = [base] + [s[1] for s in strips]

    # мощность в крейсере (постоянна: v = v_air, w = wind.speed)
    P_const = power_w(
        uav.mass_kg, uav.v_air_ms, wind.speed_ms,
        coeffs.kh, coeffs.kv, coeffs.kw,
    )

    d = np.zeros((N, N))
    t_pure = np.zeros((N, N))
    t = np.zeros((N, N))
    e = np.zeros((N, N))

    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            lat1, lon1 = exits[i]
            lat2, lon2 = entries[j]
            dist = haversine_m(lat1, lon1, lat2, lon2)
            brg = bearing_deg(lat1, lon1, lat2, lon2)
            vg = ground_speed(
                uav.v_air_ms, brg, wind.speed_ms, wind.direction_deg
            )
            vg = max(vg, 0.5)  # защита от деления на ноль
            tp = dist / vg
            turn = 0.0
            if i > 0 and j > 0:
                turn = turn_time
            elif apply_turn_to_base:
                turn = turn_time
            d[i, j] = dist
            t_pure[i, j] = tp
            t[i, j] = tp + turn
            e[i, j] = P_const * t[i, j] / 3600.0

    tau = np.zeros(M)
    eps = np.zeros(M)
    for s in range(M):
        (lat_s, lon_s), (lat_e, lon_e) = strips[s]
        L = haversine_m(lat_s, lon_s, lat_e, lon_e)
        brg = bearing_deg(lat_s, lon_s, lat_e, lon_e)
        vg = ground_speed(
            uav.v_air_ms, brg, wind.speed_ms, wind.direction_deg
        )
        vg = max(vg, 0.5)
        tau[s] = L / vg
        eps[s] = P_const * tau[s] / 3600.0

    # взлёт / посадка
    T_takeoff = altitude_m / uav.v_vertical_ms
    T_landing = T_takeoff
    P_hover = coeffs.kh * uav.mass_kg
    E_takeoff = P_hover * T_takeoff / 3600.0
    E_landing = E_takeoff

    T_max = uav.max_flight_time_s - T_takeoff - T_landing
    E_max = uav.battery_wh - E_takeoff - E_landing

    # 1D-ключ для упорядочивания полос (ось с наибольшим разбросом)
    entries_arr = np.array([entries[i] for i in range(1, N)])
    lons = entries_arr[:, 1]
    lats = entries_arr[:, 0]
    order_key = lats if lats.std() > lons.std() else lons

    return {
        "M": M, "N": N,
        "entries": entries, "exits": exits,
        "d": d, "t_pure": t_pure, "t": t, "e": e,
        "tau": tau, "eps": eps,
        "T_takeoff": T_takeoff, "T_landing": T_landing,
        "E_takeoff": E_takeoff, "E_landing": E_landing,
        "T_max": T_max, "E_max": E_max,
        "altitude_m": altitude_m,
        "P_const": P_const,
        "order_key": order_key,
    }
