"""Матрицы времени и энергии для routing (n = VPP + M полос).

Учитывает:
  - ветер (векторный),
  - Δh между полосами (набор высоты),
  - обход препятствий на перелётах,
  - реальное время съёмки полосы (t_survey_actual_s).

Узлы:
    0      — VPP
    i>0    — swath[i-1]

Перелёт i → j считается как: exit_i → entry_j.
Это позволяет reverse полос (boustrophedon) реально влиять на маршрут.
"""

from __future__ import annotations

import numpy as np

from planner.models import Swath, VPP
from planner.physics.base import PhysicsModel, PhysicsParams
from planner.solver.obstacles import shortest_path_avoiding
from planner.utils.wind import bearing_deg, ground_speed_mps


G = 9.81


# ============================================================
# Совместимость со старым API (тесты)
# ============================================================

def build_distance_matrix(swaths: list[Swath], vpp: VPP, fwd):
    """Матрица центров. Оставлено для тестов."""
    m = len(swaths)
    n = m + 1
    dist = np.zeros((n, n), dtype=float)

    pts = [(vpp.lon, vpp.lat)]
    for s in swaths:
        lat = (s.start.lat + s.end.lat) / 2.0
        lon = (s.start.lon + s.end.lon) / 2.0
        pts.append((lon, lat))

    xy = [fwd.transform(lon, lat) for lon, lat in pts]

    for i in range(n):
        for j in range(n):
            if i != j:
                dx = xy[i][0] - xy[j][0]
                dy = xy[i][1] - xy[j][1]
                dist[i, j] = float(np.hypot(dx, dy))

    return dist, xy


# ============================================================
# Путь: длина, время, waypoints
# ============================================================

def _leg_time(
    wps: list[tuple[float, float]],
    v_air: float,
    wind_speed: float,
    wind_dir: float,
) -> float:
    """Сумма времени по всем legs с учётом ветра."""
    t = 0.0
    for k in range(len(wps) - 1):
        pa, pb = wps[k], wps[k + 1]
        d = float(np.hypot(pb[0] - pa[0], pb[1] - pa[1]))
        if d < 1e-6:
            continue
        br = bearing_deg(pa[0], pa[1], pb[0], pb[1])
        v_g = ground_speed_mps(v_air, br, wind_speed, wind_dir)
        t += d / v_g
    return t


# ============================================================
# Основная функция
# ============================================================

def build_time_energy_matrices(
    swaths: list[Swath],
    vpp: VPP,
    fwd,
    physics: PhysicsModel,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
    obstacles_m: list | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Возвращает (t_ij, e_ij, t_survey).

    Узлы: 0 = VPP, i>0 = swath[i-1].
    Перелёт i → j: exit_i → entry_j (obstacle-aware).
    """
    obstacles_m = obstacles_m or []
    m = len(swaths)
    n = m + 1

    # --- Координаты узлов ---
    # Из i выходим с конца (end), приходим в j на начало (start).
    entries_xy: list[tuple[float, float]] = [fwd.transform(vpp.lon, vpp.lat)]
    exits_xy: list[tuple[float, float]] = [fwd.transform(vpp.lon, vpp.lat)]
    for s in swaths:
        entries_xy.append(fwd.transform(s.start.lon, s.start.lat))
        exits_xy.append(fwd.transform(s.end.lon, s.end.lat))

    # --- Высоты входа / выхода ---
    h_entry = np.zeros(n, dtype=float)
    h_exit = np.zeros(n, dtype=float)
    h_entry[0] = h_exit[0] = vpp.alt_m
    for i, s in enumerate(swaths, start=1):
        h_entry[i] = s.h_asl_entry_m or s.h_asl_m
        h_exit[i] = s.h_asl_exit_m or s.h_asl_m

    t_ij = np.zeros((n, n), dtype=float)
    e_ij = np.zeros((n, n), dtype=float)

    P_nominal_w = physics.power_w(params.v_air_mps, wind_speed_mps)
    v_climb = max(params.v_climb_mps, 0.5)

    # --- Расчёт перелётов ---
    for i in range(n):
        for j in range(n):
            if i == j:
                continue

            # Из i выходим с конца, приходим в j на начало
            p_from = exits_xy[i]
            p_to = entries_xy[j]

            # Obstacle-aware путь
            _, wps = shortest_path_avoiding(p_from, p_to, obstacles_m)

            # Время полёта по waypoints (с ветром)
            t_flight = _leg_time(
                wps, params.v_air_mps, wind_speed_mps, wind_direction_deg,
            )

            # Δh: от высоты выхода i к высоте входа j
            dh = h_entry[j] - h_exit[i]
            t_climb = max(dh, 0.0) / v_climb

            t = t_flight + params.t_turn_s + t_climb
            t_ij[i, j] = t

            # Энергия: полёт + набор высоты
            e_flight = P_nominal_w * t_flight / 3600.0
            e_climb = params.mass_kg * G * max(dh, 0.0) / 3600.0
            e_ij[i, j] = e_flight + e_climb

    # --- Время съёмки полосы ---
    t_survey = np.zeros(n, dtype=float)
    for i, s in enumerate(swaths, start=1):
        if s.t_survey_actual_s > 0:
            t_survey[i] = s.t_survey_actual_s
        else:
            t_survey[i] = s.length_m / max(params.v_survey_mps, 0.5)

    return t_ij, e_ij, t_survey