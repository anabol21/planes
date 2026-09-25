"""Матрицы времени и энергии для пар полос одного борта (с векторным ветром)."""

from __future__ import annotations

import numpy as np

from planner.models import Swath, VPP
from planner.physics.base import PhysicsModel, PhysicsParams
from planner.utils.wind import bearing_deg, ground_speed_mps


def build_distance_matrix(
    swaths: list[Swath],
    vpp: VPP,
    fwd,
) -> np.ndarray:
    """
    Матрица расстояний (метры) размера (M+1)×(M+1).
    Индекс 0 — ВПП, индексы 1..M — полосы.
    """
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


def build_time_energy_matrices(
    swaths: list[Swath],
    vpp: VPP,
    fwd,
    physics: PhysicsModel,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Возвращает (t_ij, e_ij, t_survey).

    t_ij — время перелёта между центрами (сек), учитывает векторный ветер:
        t_ij = distance / |V_ground(bearing)| + t_turn
    e_ij — энергия перелёта (Вт·ч).
    t_survey — время съёмки полосы (сек).
    """
    dist, xy = build_distance_matrix(swaths, vpp, fwd)
    n = dist.shape[0]

    t_ij = np.zeros((n, n), dtype=float)
    e_ij = np.zeros((n, n), dtype=float)

    P_w = physics.power_w(params.v_air_mps, wind_speed_mps)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            d = dist[i, j]
            br = bearing_deg(xy[i][0], xy[i][1], xy[j][0], xy[j][1])
            v_g = ground_speed_mps(
                params.v_air_mps, br, wind_speed_mps, wind_direction_deg
            )
            t = d / v_g + params.t_turn_s
            t_ij[i, j] = t
            e_ij[i, j] = P_w * t / 3600.0

    t_survey = np.zeros(n, dtype=float)
    for i, s in enumerate(swaths, start=1):
        t_survey[i] = s.length_m / max(params.v_survey_mps, 0.5)

    return t_ij, e_ij, t_survey