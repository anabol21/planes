"""Общий интерфейс: генерация полос внутри выпуклого куска.

Покрытие области: если ширина куска не кратна spacing_m, полосы
ставятся с шагом spacing_m, но так, чтобы ПОКРЫТЬ и правый край.
Это гарантирует полное покрытие области съёмки.
"""

from __future__ import annotations

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry


# Минимальная длина полосы — короче отбрасывается как артефакт клиппинга.
MIN_SWATH_LEN_M = 1.0


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


def _positions(minx: float, maxx: float, spacing: float) -> list[float]:
    """Позиции полос вдоль оси X.

    Гарантирует:
      - покрытие левого края (первая полоса на minx + spacing/2);
      - покрытие правого края (последняя полоса на maxx - spacing/2);
      - шаг ровно spacing между полосами, если ширина кратна.

    Если ширина не кратна spacing, две последние полосы идут плотнее
    (шаг < spacing), чтобы покрыть правый край. Это лучше, чем дырка.
    """
    width = maxx - minx
    if width <= 0:
        return []

    # Одна полоса — по центру
    if width <= spacing:
        return [minx + width / 2.0]

    # Сколько полос влезает с шагом spacing
    n_full = int(np.floor(width / spacing))

    # Если ширина кратна spacing с точностью — просто сетка от центра
    if abs(width - n_full * spacing) < 1e-3:
        # Чётное число полос — с центровкой
        x0 = minx + (width - (n_full - 1) * spacing) / 2.0
        return [x0 + i * spacing for i in range(n_full)]

    # Не кратно — покрываем оба края
    # Полосы: minx+spacing/2, ..., до maxx-spacing/2
    positions: list[float] = []
    x = minx + spacing / 2.0
    while x <= maxx - spacing / 2.0 + 1e-6:
        positions.append(x)
        x += spacing

    # Правый край: если последняя полоса не покрывает край — добавить
    last_x = positions[-1] if positions else minx
    right_edge = maxx - spacing / 2.0
    if last_x < right_edge - 1e-3:
        positions.append(right_edge)

    return positions


def swaths_in_piece(
    piece_m: Polygon,
    angle_deg: float,
    spacing_m: float,
) -> list[LineString]:
    """Строит параллельные галсы внутри куска.

    Args:
        piece_m: выпуклый кусок полигона в метрах.
        angle_deg: угол галсов (0 = вдоль оси Y, 90 = вдоль X).
        spacing_m: шаг между галсами (ширина полосы с учётом перекрытия).

    Returns:
        Список LineString, отсортированный по возрастанию координаты
        в исходной системе.
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be > 0")
    if piece_m.is_empty or piece_m.area < 1e-6:
        return []

    cx, cy = piece_m.centroid.x, piece_m.centroid.y
    origin = (cx, cy)

    rotated = rotate(piece_m, -angle_deg, origin=origin)
    minx, miny, maxx, maxy = rotated.bounds

    xs = _positions(minx, maxx, spacing_m)
    if not xs:
        return []

    lines: list[LineString] = []
    for x in xs:
        ray = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
        clipped = ray.intersection(rotated)
        for ln in _iter_lines(clipped):
            if ln.length >= MIN_SWATH_LEN_M:
                lines.append(ln)

    return [rotate(ln, angle_deg, origin=origin) for ln in lines]