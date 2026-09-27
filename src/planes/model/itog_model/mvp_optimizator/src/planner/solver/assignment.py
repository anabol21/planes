"""Назначение кластеров бортам: Венгерский + dummy."""

from __future__ import annotations

from scipy.optimize import linear_sum_assignment
import numpy as np

from planner.models import Cluster, UAVConfig, VPP


def _cluster_vpp_distance_m(
    cluster: Cluster,
    vpp: VPP,
) -> float:
    """Приблизительное расстояние кластер-ВПП в метрах."""
    dlat = (cluster.centroid_lat - vpp.lat) * 111_000.0
    dlon = (cluster.centroid_lon - vpp.lon) * 111_000.0 * np.cos(np.radians(vpp.lat))
    return float(np.hypot(dlat, dlon))


def assign_clusters_to_uavs(
    clusters: list[Cluster],
    uavs: list[UAVConfig],
    vpps: list[VPP],
) -> dict[str, list[Cluster]]:
    """
    Венгерский алгоритм: K кластеров → N бортов.

    K ≤ N: некоторые борта не получают кластеров (dummy).
    K > N: часть бортов получит несколько кластеров.

    Возвращает {uav_id: [cluster, ...]}.
    """
    if not uavs:
        raise ValueError("No UAVs to assign clusters")
    if not clusters:
        return {u.id: [] for u in uavs}

    n_uavs = len(uavs)
    n_clusters = len(clusters)
    size = max(n_uavs, n_clusters)

    # Квадратная матрица cost size×size
    BIG = 1e9
    cost = np.full((size, size), BIG, dtype=float)

    vpp_by_id = {v.id: v for v in vpps}

    for i, c in enumerate(clusters):
        for j, u in enumerate(uavs):
            vpp = vpp_by_id.get(u.vpp_id)
            if vpp is None:
                continue
            cost[i, j] = _cluster_vpp_distance_m(c, vpp)

    row_ind, col_ind = linear_sum_assignment(cost)

    result: dict[str, list[Cluster]] = {u.id: [] for u in uavs}

    for r, c in zip(row_ind, col_ind):
        if r >= n_clusters or c >= n_uavs:
            continue
        if cost[r, c] >= BIG:
            continue
        uav_id = uavs[c].id
        result[uav_id].append(clusters[r])

    return result