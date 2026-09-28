"""Назначение кластеров бортам: Венгерский + dummy.

Учитывает:
  - расстояние от кластера до ВПП борта (haversine);
  - совместимость камеры борта с survey_type кластера;
  - ограничения ВПП: камера разрешена (vpp.cameras),
    борт разрешён (vpp.uavs).

Несовместимые пары получают штраф BIG, Венгерский их избегает.
Если для какого-то кластера нет ни одной совместимой пары — он
остаётся нераспределённым, assignment_cost его игнорирует.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from planner.io.catalog import Catalog
from planner.models import Cluster, MissionInput, Point, UAVConfig, VPP
from planner.utils.logging import log_warn
from planner.utils.route_metrics import haversine_m


# Штраф для несовместимых пар. Достаточно большой, чтобы Венгерский
# никогда не выбрал несовместимую пару вместо совместимой.
BIG = 1e9


# ============================================================
# Метрика
# ============================================================

def _cluster_vpp_distance_m(cluster: Cluster, vpp: VPP) -> float:
    """Расстояние центроид кластера → ВПП, метры (haversine)."""
    return haversine_m(
        Point(lat=cluster.centroid_lat, lon=cluster.centroid_lon),
        Point(lat=vpp.lat, lon=vpp.lon),
    )


# ============================================================
# Совместимость
# ============================================================

def _uav_compatible_with_cluster(
    uav: UAVConfig,
    cluster: Cluster,
    mission: MissionInput,
    catalog: Catalog,
) -> tuple[bool, str]:
    """Проверяет совместимость борта с кластером.

    Returns:
        (compatible, reason).
        reason — пусто, если ок; иначе текстовая причина.
    """
    # survey_type кластера должен поддерживаться камерой
    if cluster.survey_type is not None:
        if not catalog.camera_supports(uav.camera_id, cluster.survey_type):
            return False, (
                f"камера {uav.camera_id!r} не поддерживает "
                f"survey_type={cluster.survey_type.value!r}"
            )

    # ВПП борта существует?
    try:
        vpp = mission.vpp_by_id(uav.vpp_id)
    except KeyError:
        return False, f"vpp_id={uav.vpp_id!r} не найден"

    # Камера разрешена на ВПП?
    if not vpp.has_camera(uav.camera_id):
        return False, (
            f"камера {uav.camera_id!r} не разрешена на ВПП {vpp.id!r}"
        )

    # Борт разрешён на ВПП?
    if not vpp.has_uav(uav.id):
        return False, (
            f"борт {uav.id!r} не разрешён на ВПП {vpp.id!r}"
        )

    return True, ""


# ============================================================
# Основной алгоритм
# ============================================================

def assign_clusters_to_uavs(
    clusters: list[Cluster],
    uavs: list[UAVConfig],
    vpps: list[VPP],
    mission: MissionInput | None = None,
    catalog: Catalog | None = None,
) -> dict[str, list[Cluster]]:
    """Венгерский алгоритм: K кластеров → N бортов.

    Args:
        clusters: список кластеров (из cluster_swaths).
        uavs: список бортов.
        vpps: список ВПП.
        mission: MissionInput (опционально) — для проверки
            ограничений ВПП. Если None — совместимость не
            проверяется (обратная совместимость).
        catalog: Catalog (опционально) — для проверки
            camera_supports. Если None — совместимость
            не проверяется.

    Returns:
        {uav_id: [cluster, ...]}. Все борта из uavs присутствуют,
        у неиспользованных — пустой список.
    """
    if not uavs:
        raise ValueError("No UAVs to assign clusters")

    result: dict[str, list[Cluster]] = {u.id: [] for u in uavs}

    if not clusters:
        return result

    n_uavs = len(uavs)
    n_clusters = len(clusters)
    size = max(n_uavs, n_clusters)

    cost = np.full((size, size), BIG, dtype=float)

    vpp_by_id = {v.id: v for v in vpps}

    # Заполняем реальные ячейки
    for i, c in enumerate(clusters):
        for j, u in enumerate(uavs):
            # Проверка совместимости (если есть mission + catalog)
            if mission is not None and catalog is not None:
                ok, _reason = _uav_compatible_with_cluster(
                    u, c, mission, catalog,
                )
                if not ok:
                    continue  # оставляем BIG

            vpp = vpp_by_id.get(u.vpp_id)
            if vpp is None:
                continue
            cost[i, j] = _cluster_vpp_distance_m(c, vpp)

    # Венгерский
    row_ind, col_ind = linear_sum_assignment(cost)

    for r, c in zip(row_ind, col_ind):
        if r >= n_clusters or c >= n_uavs:
            continue
        if cost[r, c] >= BIG:
            # Несовместимая пара — cluster остаётся без борта
            log_warn(
                "assignment",
                f"cluster {clusters[r].id}: нет совместимого борта",
            )
            continue
        result[uavs[c].id].append(clusters[r])

    return result


# ============================================================
# Оценка назначения (для тестов / отладки)
# ============================================================

def assignment_cost(
    assign: dict[str, list[Cluster]],
    uavs: list[UAVConfig],
    vpps: list[VPP],
) -> float:
    """Суммарная стоимость назначения в метрах.

    Стоимость = сумма расстояний центроид↔ВПП по всем назначениям.
    Несовместимые пары в стоимости не участвуют.
    """
    vpp_by_id = {v.id: v for v in vpps}
    uav_by_id = {u.id: u for u in uavs}

    total = 0.0
    for uav_id, clusters in assign.items():
        uav = uav_by_id.get(uav_id)
        if uav is None:
            continue
        vpp = vpp_by_id.get(uav.vpp_id)
        if vpp is None:
            continue
        for c in clusters:
            total += _cluster_vpp_distance_m(c, vpp)
    return total