"""Обход препятствий и запретных зон на перелётах.

Стратегия MVP:
  1. Прямая i → j. Если не пересекает — берём её.
  2. Иначе ищем путь через одну вершину препятствия
     (visibility graph: i → vertex → j).
  3. Если и это не помогает — fallback со штрафом.

Запретные зоны (NoFlyZone) обрабатываются тем же механизмом:
они передаются в тот же список barriers, что и препятствия.
Разница — семантическая (в валидаторе и в буферах), а не в
алгоритме обхода.
"""

from __future__ import annotations

import math
from typing import Iterable

from shapely.geometry import LineString, Polygon, shape


# ============================================================
# Подготовка
# ============================================================

def prepare_obstacles_m(
    obstacles_wgs: Iterable[dict],
    fwd,
) -> list[Polygon]:
    """GeoJSON-препятствия → Polygon в ENU (метры)."""
    result: list[Polygon] = []
    for obs in obstacles_wgs:
        poly = shape(obs)
        xy = [fwd.transform(x, y) for x, y in poly.exterior.coords]
        if len(xy) >= 3:
            result.append(Polygon(xy))
    return result


def prepare_no_fly_zones_m(
    no_fly_zones_wgs: Iterable[dict],
    fwd,
) -> list[Polygon]:
    """GeoJSON-запретки → Polygon в ENU (метры).

    Семантически — те же полигоны-барьеры, что и препятствия.
    Отдельная функция — для ясности в pipeline (разные буферы,
    разная валидация).
    """
    result: list[Polygon] = []
    for nfz in no_fly_zones_wgs:
        poly = shape(nfz)
        xy = [fwd.transform(x, y) for x, y in poly.exterior.coords]
        if len(xy) >= 3:
            result.append(Polygon(xy))
    return result


def prepare_barriers_m(
    obstacles_wgs: Iterable[dict],
    no_fly_zones_wgs: Iterable[dict],
    fwd,
    obstacle_buffer_m: float = 0.0,
    no_fly_buffer_m: float = 0.0,
) -> list[Polygon]:
    """Объединённый список барьеров для shortest_path_avoiding.

    Применяет буферы:
      - obstacle_buffer_m — к препятствиям (обычно 20 м);
      - no_fly_buffer_m   — к запреткам (обычно 0 м).

    Returns:
        list[Polygon] в ENU. Буференные (если buffer > 0).
    """
    obstacles_m = prepare_obstacles_m(obstacles_wgs, fwd)
    nfz_m = prepare_no_fly_zones_m(no_fly_zones_wgs, fwd)

    if obstacle_buffer_m > 0:
        obstacles_m = [o.buffer(obstacle_buffer_m) for o in obstacles_m]
    if no_fly_buffer_m > 0:
        nfz_m = [z.buffer(no_fly_buffer_m) for z in nfz_m]

    return obstacles_m + nfz_m


# ============================================================
# Проверка пересечения
# ============================================================

def _crosses_any(line: LineString, obstacles: list[Polygon]) -> bool:
    """True, если линия проходит через внутренность препятствия.

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
    """Кратчайший путь p1 → p2 в обход барьеров.

    Барьеры — любые Polygon: препятствия, запретки, их объединение.
    Алгоритм не различает их.

    Args:
        p1, p2: точки в ENU-метрах.
        obstacles: список Polygon-барьеров (препятствия + запретки).

    Returns:
        (distance_m, waypoints_xy).
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
        for vx, vy in obs.exterior.coords:
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