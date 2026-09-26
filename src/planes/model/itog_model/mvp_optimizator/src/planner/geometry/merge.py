"""Слияние тонких кусков декомпозиции."""

from __future__ import annotations

from shapely.geometry import Polygon


def _dim(p: Polygon) -> float:
    """Минимальный габарит куска (по осям X и Y)."""
    w = p.bounds[2] - p.bounds[0]
    h = p.bounds[3] - p.bounds[1]
    return min(w, h)


def _shared_length(a: Polygon, b: Polygon) -> float:
    """Длина общего ребра (границы)."""
    shared = a.boundary.intersection(b.boundary)
    if shared.is_empty:
        return 0.0
    if shared.geom_type == "LineString":
        return shared.length
    if shared.geom_type == "MultiLineString":
        return sum(g.length for g in shared.geoms)
    return 0.0


def merge_thin_pieces(
    pieces: list[Polygon],
    min_width_m: float,
    max_iter: int = 500,
    min_shared_len: float = 1.0,
    min_convexity: float = 0.4,
) -> list[Polygon]:
    """
    Объединяет соседние куски, если один из них тоньше min_width_m.

    Правила:
      - есть общее ребро длиной >= min_shared_len;
      - объединение — полигон (не MultiPolygon);
      - отношение area / convex_hull.area >= min_convexity.
    """
    pieces = [p for p in pieces if not p.is_empty and p.area > 1e-6]
    skip: set[int] = set()

    for _ in range(max_iter):
        thin_idx = None
        min_dim = float("inf")
        for i, p in enumerate(pieces):
            if i in skip:
                continue
            d = _dim(p)
            if d < min_width_m and d < min_dim:
                min_dim = d
                thin_idx = i

        if thin_idx is None:
            break

        thin = pieces[thin_idx]

        best_j = None
        best_shared = 0.0
        for j, other in enumerate(pieces):
            if j == thin_idx or j in skip:
                continue
            L = _shared_length(thin, other)
            if L > best_shared and L >= min_shared_len:
                best_shared = L
                best_j = j

        if best_j is None:
            skip.add(thin_idx)
            continue

        other = pieces[best_j]
        merged = thin.union(other)

        if merged.is_empty or merged.geom_type != "Polygon":
            skip.add(thin_idx)
            continue

        if merged.convex_hull.area > 0:
            ratio = merged.area / merged.convex_hull.area
            if ratio < min_convexity:
                skip.add(thin_idx)
                continue

        pieces = [p for k, p in enumerate(pieces) if k not in (thin_idx, best_j)]
        skip = set()
        pieces.append(merged)

    return pieces