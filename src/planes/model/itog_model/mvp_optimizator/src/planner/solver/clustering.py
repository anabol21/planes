"""K-Means кластеризация полос: K = N (один кластер на борт)."""

from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans

from planner.models import Cluster, Swath


def _swath_centroid(swath: Swath) -> tuple[float, float]:
    lat = (swath.start.lat + swath.end.lat) / 2.0
    lon = (swath.start.lon + swath.end.lon) / 2.0
    return lat, lon


def cluster_swaths(swaths: list[Swath], k: int, random_state: int = 42) -> list[Cluster]:
    """
    K-Means по (lat, lon) центроидам полос.
    K = число бортов, один кластер = один борт.
    """
    if not swaths:
        return []
    if k < 1:
        raise ValueError("k must be >= 1")

    if k == 1:
        centroids = [_swath_centroid(s) for s in swaths]
        clat = sum(c[0] for c in centroids) / len(centroids)
        clon = sum(c[1] for c in centroids) / len(centroids)
        return [
            Cluster(
                id="cluster-0",
                swath_ids=[s.id for s in swaths],
                centroid_lat=clat,
                centroid_lon=clon,
            )
        ]

    coords = np.array([_swath_centroid(s) for s in swaths], dtype=float)
    n_clusters = min(k, len(swaths))

    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state)
    labels = km.fit_predict(coords)

    clusters: list[Cluster] = []
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        swath_ids = [swaths[i].id for i in idx]
        center = km.cluster_centers_[cid]
        clusters.append(
            Cluster(
                id=f"cluster-{cid}",
                swath_ids=swath_ids,
                centroid_lat=float(center[0]),
                centroid_lon=float(center[1]),
            )
        )

    return clusters