"""Terrain following по коридору.

Идея:
  1. Считаем для каждой waypoint h_min = DEM + safety_margin
     и h_target = DEM + h_agl_target.
  2. Прямой проход: h[i] = max(h_target[i], h[i-1])
     (поднимаемся сразу, но не спускаемся).
  3. Обратный проход: h[i] = min(h[i], max(h_target[i], h[i+1]))
     (спускаемся только если впереди реально ниже).
  4. Опционально — сглаживание окном.
  5. Финальная проверка: h[i] ≥ h_min[i].
"""

from __future__ import annotations

from planner.models import Point


def terrain_corridor(
    waypoints: list[Point],
    dem,
    h_agl_target_m: float,
    safety_margin_m: float,
    smooth_window: int = 5,
) -> list[Point]:
    """
    Преобразует waypoints так, чтобы высота шла «коридором»:
    горизонтально, когда возможно.

    Args:
        waypoints: точки с lat/lon/alt_m (alt_m перезапишется)
        dem: DEM-объект с .h(lat, lon)
        h_agl_target_m: желаемая высота над рельефом (из GSD)
        safety_margin_m: минимальный зазор
        smooth_window: размер окна сглаживания (0 = без сглаживания)

    Returns:
        Новый список Point (не мутирует исходный).
    """
    if not waypoints or dem is None:
        return [Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m) for p in waypoints]

    try:
        if dem.is_empty():
            return [Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m) for p in waypoints]
    except AttributeError:
        return [Point(lat=p.lat, lon=p.lon, alt_m=p.alt_m) for p in waypoints]

    n = len(waypoints)
    h_min = [0.0] * n
    h_target = [0.0] * n
    dem_h = [0.0] * n

    for i, p in enumerate(waypoints):
        d = dem.h(p.lat, p.lon)
        dem_h[i] = d
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
        # Максимум по окну вперёд
        window_end = min(n, i + 10)
        future_max = max(h_target[i:window_end])
        target = max(h_target[i], h_min[i], future_max)
        h[i] = min(h[i], target)

    # 3. Сглаживание окном (moving average)
    if smooth_window and smooth_window >= 3 and n >= smooth_window:
        h_s = h[:]
        half = smooth_window // 2
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            avg = sum(h[lo:hi]) / (hi - lo)
            # Никогда не ниже безопасного минимума
            h_s[i] = max(avg, h_min[i])
        h = h_s

    # 4. Финальная проверка
    for i in range(n):
        if h[i] < h_min[i]:
            h[i] = h_min[i]

    return [
        Point(lat=waypoints[i].lat, lon=waypoints[i].lon, alt_m=h[i])
        for i in range(n)
    ]