"""Трапециевидная декомпозиция: полигон → набор вертикальных трапеций."""

from __future__ import annotations

from shapely.geometry import Polygon, box


def _all_x(poly: Polygon) -> list[float]:
    xs: set[float] = set()
    xs.update(p[0] for p in poly.exterior.coords)
    for interior in poly.interiors:
        xs.update(p[0] for p in interior.coords)
    return sorted(xs)


def trapezoid_decomposition(poly: Polygon) -> list[Polygon]:
    """Режет полигон вертикальными линиями через каждую вершину."""
    if poly.is_empty:
        return []

    xs = _all_x(poly)
    if len(xs) < 2:
        return [poly]

    miny, maxy = poly.bounds[1], poly.bounds[3]
    pieces: list[Polygon] = []

    for x1, x2 in zip(xs[:-1], xs[1:]):
        if x2 - x1 < 1e-6:
            continue
        strip = box(x1, miny - 1.0, x2, maxy + 1.0)
        inter = poly.intersection(strip)
        if inter.is_empty:
            continue
        if inter.geom_type == "Polygon":
            pieces.append(inter)
        elif inter.geom_type == "MultiPolygon":
            pieces.extend(inter.geoms)
        # GeometryCollection тоже возможен — фильтруем
        elif inter.geom_type == "GeometryCollection":
            for g in inter.geoms:
                if g.geom_type == "Polygon":
                    pieces.append(g)

    return pieces