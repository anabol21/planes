"""Матрицы времени и энергии для пар полос одного борта."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Point as ShPoint
from shapely.geometry import Polygon

from planner.models import Point, Swath, VPP
from planner.physics.base import PhysicsModel, PhysicsParams


def _swath_center_xy(swath: Swath, fwd) -> tuple[float, float]:
    """Центр полосы в локальных метрах."""
    lat = (swath.start.lat + swath.end.lat) / 2.0
    lon = (swath.start.lon + swath.end.lon) / 2.0
    x, y = fwd.transform(lon, lat)
    return float(x), float(y)


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

    # Точки: 0 = VPP, i = center(swath[i-1])
    pts = [(vpp.lon, vpp.lat)]
    for s in swaths:
        lat = (s.start.lat + s.end.lat) / 2.0
        lon = (s.start.lon + s.end.lon) / 2.0
        pts.append((lon, lat))

    xy = [fwd.transform(lon, lat) for lon, lat in pts]

    for i in range(n):
        for j in range(n):
            if i == j:
                dist[i, j] = 0.0
            else:
                dx = xy[i][0] - xy[j][0]
                dy = xy[i][1] - xy[j][1]
                dist[i, j] = float(np.hypot(dx, dy))

    return dist


def build_time_energy_matrices(
    swaths: list[Swath],
    vpp: VPP,
    fwd,
    physics: PhysicsModel,
    params: PhysicsParams,
    wind_mps: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Возвращает (t_ij, e_ij, t_survey).
    t_ij — время перелёта между центрами (сек).
    e_ij — энергия перелёта (Вт·ч).
    t_survey — время съёмки каждой полосы (сек).
    """
    dist = build_distance_matrix(swaths, vpp, fwd)

    v_ground = physics.ground_speed_mps(params.v_air_mps, wind_mps)
    v_ground = max(v_ground, 0.5)

    t_ij = dist / v_ground
    # + фиксированная надбавка за разворот
    t_ij = t_ij + params.t_turn_s * (dist > 0.0).astype(float)

    P_w = physics.power_w(params.v_air_mps, wind_mps)
    e_ij = P_w * t_ij / 3600.0

    # Съёмка вдоль полосы
    t_survey = np.zeros(len(swaths) + 1, dtype=float)
    for i, s in enumerate(swaths, start=1):
        t_survey[i] = s.length_m / max(params.v_survey_mps, 0.5)

    return t_ij, e_ij, t_survey