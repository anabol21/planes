"""Триангуляция полигона + жадное слияние выпуклых соседей."""

from __future__ import annotations

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import triangulate


def _as_polygon(geom) -> Polygon | None:
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        # берём самый крупный кусок
        return max(geom.geoms, key=lambda g: g.area)
    return None


def _is_convex(poly: Polygon, eps: float = 1e-6) -> bool:
    """Проверка выпуклости по площади с convex_hull."""
    return abs(poly.area - poly.convex_hull.area) < eps * max(poly.area, 1.0)


def _share_edge(a: Polygon, b: Polygon, tol: float = 1e-3) -> bool:
    """Есть ли общее ребро длиной > tol."""
    shared = a.boundary.intersection(b.boundary)
    if shared.is_empty:
        return False
    if shared.geom_type == "LineString":
        return shared.length > tol
    if shared.geom_type == "MultiLineString":
        return sum(g.length for g in shared.geoms) > tol
    return False


def triangulation_decomposition(
    poly: Polygon,
    area_eps: float = 1e-6,
    max_merge_iters: int = 100,
) -> list[Polygon]:
    """
    1) Delaunay-триангуляция вершин.
    2) Отсечение по полигону (учёт дырок).
    3) Жадное слияние соседних выпуклых кусков.
    """
    if poly.is_empty:
        return []

    # 1) Триангуляция выпуклой оболочки вершин
    raw_tris = triangulate(poly)
    pieces: list[Polygon] = []

    # 2) Отсечение и фильтр тонких
    for tri in raw_tris:
        inter = tri.intersection(poly)
        p = _as_polygon(inter)
        if p is not None and p.area > area_eps:
            pieces.append(p)

    if not pieces:
        return [poly]

    # 3) Жадное слияние
    for _ in range(max_merge_iters):
        merged = False
        n = len(pieces)
        i = 0
        while i < n and not merged:
            j = i + 1
            while j < n:
                a, b = pieces[i], pieces[j]
                if _share_edge(a, b):
                    union = a.union(b)
                    if _is_convex(union):
                        pieces[i] = union
                        pieces.pop(j)
                        merged = True
                        break
                j += 1
            i += 1
        if not merged:
            break

    return pieces