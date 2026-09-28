"""K-Means кластеризация полос: K = N (один кластер на борт).

Также содержит group_swaths_by_area — простую группировку полос по
бортам через назначение областей (для гетерогенного режима).

Каждый кластер хранит метаданные:
  - survey_type: общий тип съёмки полос кластера;
  - area_ids: какие области представлены.

Это позволяет assignment.py и pipeline.py проверять совместимость
и не смешивать разные типы съёмки в одном кластере.
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans

from planner.models import Cluster, SurveyType, Swath


_M_PER_DEG_LAT = 111_320.0


# ============================================================
# Геометрия
# ============================================================

def _swath_centroid(swath: Swath) -> tuple[float, float]:
    """Центроид полосы в градусах: (lat, lon)."""
    lat = (swath.start.lat + swath.end.lat) / 2.0
    lon = (swath.start.lon + swath.end.lon) / 2.0
    return lat, lon


def _to_local_meters(
    coords_deg: np.ndarray,
    mean_lat_rad: float,
) -> np.ndarray:
    out = coords_deg.copy()
    out[:, 0] = coords_deg[:, 0] * _M_PER_DEG_LAT
    out[:, 1] = (
        coords_deg[:, 1] * _M_PER_DEG_LAT * np.cos(mean_lat_rad)
    )
    return out


def _from_local_meters(
    coords_m: np.ndarray,
    mean_lat_rad: float,
) -> np.ndarray:
    out = coords_m.copy()
    out[:, 0] = coords_m[:, 0] / _M_PER_DEG_LAT
    cos_lat = max(float(np.cos(mean_lat_rad)), 1e-6)
    out[:, 1] = coords_m[:, 1] / (_M_PER_DEG_LAT * cos_lat)
    return out


# ============================================================
# Метаданные кластера
# ============================================================

def _cluster_metadata(
    swaths: list[Swath],
    mission,
) -> tuple[SurveyType | None, list[str]]:
    """Определяет общий survey_type и список area_ids полос кластера.

    Args:
        swaths: полосы кластера.
        mission: MissionInput с областями (для чтения survey_type).

    Returns:
        (survey_type | None, area_ids).
        survey_type = None, если в кластере полосы разных типов.
    """
    area_by_id = {a.id: a for a in mission.areas}

    survey_types: set[SurveyType] = set()
    area_ids: set[str] = set()

    for s in swaths:
        area_ids.add(s.area_id)
        area = area_by_id.get(s.area_id)
        if area is not None:
            survey_types.add(area.survey_type)

    survey_type: SurveyType | None = None
    if len(survey_types) == 1:
        survey_type = next(iter(survey_types))

    return survey_type, sorted(area_ids)


# ============================================================
# K-Means
# ============================================================

def cluster_swaths(
    swaths: list[Swath],
    k: int,
    mission=None,
    random_state: int = 42,
) -> list[Cluster]:
    """K-Means по центроидам полос в локальных метрах.

    Args:
        swaths: список полос.
        k: желаемое число кластеров.
        mission: MissionInput (опционально) — для заполнения
            survey_type и area_ids в кластере.
        random_state: seed.

    Returns:
        Список Cluster. Длина ≤ min(k, len(swaths)).
    """
    if not swaths:
        return []
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    coords_deg = np.array(
        [_swath_centroid(s) for s in swaths], dtype=float
    )
    mean_lat_rad = float(np.radians(coords_deg[:, 0].mean()))

    # K = 1 — тривиально
    if k == 1:
        clat = float(coords_deg[:, 0].mean())
        clon = float(coords_deg[:, 1].mean())
        survey_type: SurveyType | None = None
        area_ids: list[str] = []
        if mission is not None:
            survey_type, area_ids = _cluster_metadata(swaths, mission)
        else:
            area_ids = sorted({s.area_id for s in swaths})
        return [
            Cluster(
                id="cluster-0",
                swath_ids=[s.id for s in swaths],
                centroid_lat=clat,
                centroid_lon=clon,
                survey_type=survey_type,
                area_ids=area_ids,
            )
        ]

    n_clusters = min(k, len(swaths))
    coords_m = _to_local_meters(coords_deg, mean_lat_rad)

    km = KMeans(
        n_clusters=n_clusters,
        n_init=10,
        random_state=random_state,
    )
    labels = km.fit_predict(coords_m)

    centers_deg = _from_local_meters(
        km.cluster_centers_.astype(float), mean_lat_rad,
    )

    clusters: list[Cluster] = []
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        cluster_swaths_list = [swaths[i] for i in idx]

        survey_type: SurveyType | None = None
        area_ids: list[str] = []
        if mission is not None:
            survey_type, area_ids = _cluster_metadata(
                cluster_swaths_list, mission,
            )
        else:
            area_ids = sorted({s.area_id for s in cluster_swaths_list})

        clusters.append(
            Cluster(
                id=f"cluster-{cid}",
                swath_ids=[s.id for s in cluster_swaths_list],
                centroid_lat=float(centers_deg[cid, 0]),
                centroid_lon=float(centers_deg[cid, 1]),
                survey_type=survey_type,
                area_ids=area_ids,
            )
        )

    return clusters


# ============================================================
# Гетерогенный режим: группировка по областям
# ============================================================

def group_swaths_by_area(
    swaths_by_area: dict[str, list[Swath]],
    area_to_uav: dict[str, str],
) -> dict[str, list[Swath]]:
    """Группирует полосы по бортам через назначение областей.

    Используется вместо K-Means в hetero-режиме.
    """
    result: dict[str, list[Swath]] = {}
    for area_id, swaths in swaths_by_area.items():
        uav_id = area_to_uav.get(area_id)
        if uav_id is None:
            continue
        result.setdefault(uav_id, []).extend(swaths)
    return result