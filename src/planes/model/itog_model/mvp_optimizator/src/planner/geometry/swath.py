"""Общий интерфейс: генерация полос внутри выпуклого куска."""

from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry


def _iter_lines(geom: BaseGeometry) -> list[LineString]:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(_iter_lines(g))
        return out
    return []


def swaths_in_piece(
    piece_m: Polygon,
    angle_deg: float,
    spacing_m: float,
) -> list[LineString]:
    """
    Строит параллельные галсы внутри куска.
    angle_deg — угол галсов (0 = вдоль оси Y, 90 = вдоль X).
    spacing_m — шаг между галсами (ширина полосы с учётом перекрытия).
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be > 0")
    if piece_m.is_empty or piece_m.area < 1e-6:
        return []

    cx, cy = piece_m.centroid.x, piece_m.centroid.y
    origin = (cx, cy)

    # Поворачиваем, чтобы галсы шли вдоль Y
    rotated = rotate(piece_m, -angle_deg, origin=origin)
    minx, miny, maxx, maxy = rotated.bounds

    lines: list[LineString] = []
    x = minx + spacing_m / 2.0
    while x <= maxx:
        ray = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
        clipped = ray.intersection(rotated)
        lines.extend(_iter_lines(clipped))
        x += spacing_m

    # Поворачиваем обратно
    return [rotate(ln, angle_deg, origin=origin) for ln in lines if ln.length > 1.0]