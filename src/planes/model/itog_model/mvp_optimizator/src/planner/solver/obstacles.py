"""Обход препятствий на перелётах между полосами.

Стратегия MVP:
  1. Прямая i → j. Если не пересекает — берём её.
  2. Иначе ищем путь через одну вершину препятствия
     (visibility graph: i → vertex → j).
  3. Если и это не помогает — fallback со штрафом.
"""

from __future__ import annotations

import math
from typing import Iterable

from shapely.geometry import LineString, Polygon, shape


# ============================================================
# Подготовка
# ============================================================

def prepare_obstacles_m(obstacles_wgs: Iterable[dict], fwd) -> list[Polygon]:
    """GeoJSON-препятствия → Polygon в ENU (метры)."""
    result: list[Polygon] = []
    for obs in obstacles_wgs:
        poly = shape(obs)
        xy = [fwd.transform(x, y) for x, y in poly.exterior.coords]
        if len(xy) >= 3:
            result.append(Polygon(xy))
    return result


# ============================================================
# Проверка пересечения
# ============================================================

def _crosses_any(line: LineString, obstacles: list[Polygon]) -> bool:
    """
    True, если линия проходит через внутренность препятствия.
    Игнорируем касания в одной точке и пересечение только по границе.
    """
    for obs in obstacles:
        inter = line.intersection(obs)
        if inter.is_empty:
            continue

        gt = inter.geom_type
        if gt in ("LineString", "MultiLineString"):
            if inter.length > 0.5:
                return True
        elif gt == "GeometryCollection":
            for g in inter.geoms:
                if g.geom_type == "LineString" and g.length > 0.5:
                    return True
                if g.geom_type == "MultiLineString":
                    if sum(x.length for x in g.geoms) > 0.5:
                        return True
    return False


# ============================================================
# Поиск пути
# ============================================================

def shortest_path_avoiding(
    p1: tuple[float, float],
    p2: tuple[float, float],
    obstacles: list[Polygon],
) -> tuple[float, list[tuple[float, float]]]:
    """
    Кратчайший путь p1 → p2 в обход препятствий.

    Возвращает (distance_m, waypoints_xy).
    Waypoints всегда начинаются с p1 и заканчиваются p2.
    """
    # Прямая без препятствий
    if not obstacles:
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        return d, [p1, p2]

    direct = LineString([p1, p2])
    if not _crosses_any(direct, obstacles):
        return direct.length, [p1, p2]

    # Путь через одну вершину (visibility)
    best_d = float("inf")
    best_v: tuple[float, float] | None = None

    for obs in obstacles:
        # Немного «раздуваем» вершины наружу — чтобы не резать границу
        for vx, vy in obs.exterior.coords:
            # Проверка: p1 → vertex → p2 не пересекает ничего
            seg1 = LineString([p1, (vx, vy)])
            seg2 = LineString([(vx, vy), p2])

            if _crosses_any(seg1, obstacles):
                continue
            if _crosses_any(seg2, obstacles):
                continue

            d = seg1.length + seg2.length
            if d < best_d:
                best_d = d
                best_v = (vx, vy)

    if best_v is not None:
        return best_d, [p1, best_v, p2]

    # Fallback: штрафуем прямую
    return direct.length * 1.3, [p1, p2]