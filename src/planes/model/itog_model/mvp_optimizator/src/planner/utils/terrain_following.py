"""Terrain following по коридору.

Идея:
  1. Считаем для каждой waypoint h_min = DEM + safety_margin
     и h_target = DEM + h_agl_target.
  2. Прямой проход: h[i] = max(h_target[i], h[i-1])
     (поднимаемся сразу, но не спускаемся).
  3. Обратный проход: h[i] = min(h[i], max(h_target[i], h[i+1]))
     (спускаемся только если впереди реально ниже).
  4. Опционально — сглаживание окном (адаптивное).
  5. Финальная проверка: h[i] ≥ h_min[i] для всех i.

Сглаживание — moving average с адаптивным окном:
  - на коротких массивах окно уменьшается;
  - после сглаживания высота не может стать ниже h_min (иначе
    профиль получит пилу — вместо этого сохраняем исходное значение).
"""

from __future__ import annotations

import numpy as np

from planner.models import Point


def _adaptive_window(n: int, requested: int) -> int:
    """Адаптивное окно сглаживания.

    - На n < 5 — окно не применяется (0).
    - На n = 5..20 — ограничено n // 3.
    - На n > 20 — запрошенное, но не больше n // 5.

    Возвращает нечётное число (или 0, если сглаживание выключено).
    """
    if requested < 3:
        return 0
    if n < 5:
        return 0
    if n <= 20:
        w = min(requested, max(3, n // 3))
    else:
        w = min(requested, max(3, n // 5))
    # Сделать нечётным для симметричного окна
    if w % 2 == 0:
        w = max(3, w - 1)
    return w


def _smooth_adaptive(
    h: list[float],
    h_min: list[float],
    window: int,
) -> list[float]:
    """Скользящее среднее с защитой h_min.

    Важно: если после сглаживания в точке h < h_min, мы НЕ поднимаем её
    принудительно (это давало бы пилу). Вместо этого сохраняем исходное
    значение h[i] из прямого/обратного прохода — оно уже ≥ h_min.
    """
    n = len(h)
    if window < 3 or n < window:
        return h

    half = window // 2
    out = h[:]
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        avg = sum(h[lo:hi]) / (hi - lo)
        # Если сглаженное значение ниже безопасного минимума — оставляем
        # оригинал (он валиден после шагов 1–2 и финальной проверки).
        if avg < h_min[i]:
            out[i] = h[i]
        else:
            out[i] = avg
    return out


def terrain_corridor(
    waypoints: list[Point],
    dem,
    h_agl_target_m: float,
    safety_margin_m: float,
    smooth_window: int = 5,
) -> list[Point]:
    """Преобразует waypoints так, чтобы высота шла «коридором»:
    горизонтально, когда возможно.

    Args:
        waypoints: точки с lat/lon/alt_m (alt_m перезапишется).
        dem: DEM-объект с .h(lat, lon).
        h_agl_target_m: желаемая высота над рельефом (из GSD).
        safety_margin_m: минимальный зазор.
        smooth_window: запрошенный размер окна (адаптивно уменьшается).

    Returns:
        Новый список Point (не мутирует исходный).
    """
    if not waypoints or dem is None:
        return [Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m) for p in waypoints]

    try:
        if dem.is_empty():
            return [
                Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m)
                for p in waypoints
            ]
    except AttributeError:
        return [Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m) for p in waypoints]

    n = len(waypoints)
    h_min = [0.0] * n
    h_target = [0.0] * n

    for i, p in enumerate(waypoints):
        d = dem.h(p.lat, p.lon)
        h_min[i] = d + safety_margin_m
        h_target[i] = d + h_agl_target_m

    # 1. Прямой проход: не спускаемся
    h = [0.0] * n
    h[0] = max(h_target[0], h_min[0])
    for i in range(1, n):
        h[i] = max(h_target[i], h[i - 1])
        if h[i] < h_min[i]:
            h[i] = h_min[i]

    # 2. Обратный проход: спускаемся только если впереди долго ниже
    h[n - 1] = max(h_target[n - 1], h_min[n - 1])
    for i in range(n - 2, -1, -1):
        window_end = min(n, i + 10)
        future_max = max(h_target[i:window_end])
        target = max(h_target[i], h_min[i], future_max)
        h[i] = min(h[i], target)

    # 3. Сглаживание — адаптивное окно + защита h_min
    w = _adaptive_window(n, smooth_window)
    if w >= 3:
        h = _smooth_adaptive(h, h_min, w)

    # 4. Финальная проверка (страховка)
    for i in range(n):
        if h[i] < h_min[i]:
            h[i] = h_min[i]

    return [
        Point(lat=waypoints[i].lat, lon=waypoints[i].lon, alt_m=h[i])
        for i in range(n)
    ]


def terrain_range_m(waypoints: list[Point], dem) -> float:
    """Перепад рельефа по всем waypoints: max(DEM) − min(DEM).

    Используется для адаптивного safety_margin_factor:
    финальный margin = max(base_margin, range · factor).

    Возвращает 0.0, если DEM отсутствует или пустой.
    """
    if not waypoints or dem is None:
        return 0.0
    try:
        if dem.is_empty():
            return 0.0
    except AttributeError:
        return 0.0

    dem_vals = [dem.h(p.lat, p.lon) for p in waypoints]
    if not dem_vals:
        return 0.0
    return float(max(dem_vals) - min(dem_vals))


def dem_range_over_area(dem, minx: float, miny: float,
                        maxx: float, maxy: float) -> float:
    """Перепад рельефа на прямоугольнике (грубо, через 3×3 сетку).

    Для адаптивного safety_margin_factor, когда waypoints ещё нет
    (например, до генерации полос).

    Возвращает max(DEM) − min(DEM) по 9 точкам сетки. 0.0, если DEM нет.
    """
    if dem is None:
        return 0.0
    try:
        if dem.is_empty():
            return 0.0
    except AttributeError:
        return 0.0

    vals: list[float] = []
    for fx in (0.0, 0.5, 1.0):
        for fy in (0.0, 0.5, 1.0):
            # Берём точки в WGS84: minx..maxx (lon), miny..maxy (lat)
            lon = minx + (maxx - minx) * fx
            lat = miny + (maxy - miny) * fy
            vals.append(dem.h(lat, lon))
    if not vals:
        return 0.0
    return float(max(vals) - min(vals))