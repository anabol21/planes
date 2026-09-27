"""Векторный ветер: компоненты, путевая скорость, время перелёта."""

from __future__ import annotations

import math


def wind_components(speed_mps: float, direction_deg: float) -> tuple[float, float]:
    """
    Разложение ветра на компоненты (w_x, w_y) в локальных метрах.
    direction_deg — куда дует ветер (метеорологическое направление,
    0° = север, 90° = восток).
    """
    rad = math.radians(direction_deg)
    # Метео: направление «откуда дует», но для простоты берём «куда»
    return speed_mps * math.sin(rad), speed_mps * math.cos(rad)


def ground_speed_mps(
    v_air_mps: float,
    bearing_deg: float,
    wind_speed_mps: float,
    wind_direction_deg: float,
) -> float:
    """
    Путевая скорость на данном курсе с учётом ветра.

    bearing_deg — курс полёта (0 = север, 90 = восток).
    Возвращает модуль |V_ground|.

    Если V_ground слишком мал (<0.5 м/с) — возвращает 0.5 (защита).
    """
    wx, wy = wind_components(wind_speed_mps, wind_direction_deg)
    br = math.radians(bearing_deg)
    vx = v_air_mps * math.sin(br) + wx
    vy = v_air_mps * math.cos(br) + wy
    speed = math.hypot(vx, vy)
    return max(speed, 0.5)


def bearing_deg(x1: float, y1: float, x2: float, y2: float) -> float:
    """Курс из точки 1 в точку 2 (0 = север, 90 = восток)."""
    dx = x2 - x1
    dy = y2 - y1
    return (math.degrees(math.atan2(dx, dy))) % 360.0