"""Мультиротор: Gemini, Geoscan 801.

Модель мощности:
    P = k_h·m + k_v·v³

где:
  - k_h = 90 Вт/кг — весовая составляющая (висение);
  - k_v = 0.02 Вт·с³/м³ — паразитное сопротивление.

Влияние ветра на мощность НЕ моделируется (согласно указаниям
организаторов). Ветер влияет только на время перелёта через
V_ground. Запас на маневрирование и погоду — reserve_fraction = 0.15.

Калибровка: для Gemini (m=2 кг, v=12 м/с):
    P = 90·2 + 0.02·1728 = 180 + 34.56 = 214.56 Вт
    T_flight = 144.7 Вт·ч / 214.56 Вт = 40.5 мин ≈ паспортные 40 мин.
"""

from __future__ import annotations

from planner.physics.base import PhysicsModel, PhysicsParams


class RotorPhysics(PhysicsModel):
    """P = k_h·m + k_v·v³ (без k_w)."""

    def __init__(self, p: PhysicsParams):
        self.p = p

    def power_w(self, v_air_mps: float, wind_mps: float) -> float:
        """Мощность мультиротора.

        Ветер (wind_mps) НЕ используется — оставлен в сигнатуре
        для обратной совместимости с вызовами:
            model.power_w(v_air, wind_speed)
        """
        p = self.p
        return p.k_h * p.mass_kg + p.k_v * (v_air_mps ** 3)

    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float:
        """Worst-case путевая скорость (полёт строго против ветра).

        Для маршрутизации с направлением ветра используется
        planner.utils.wind.ground_speed_mps(v_air, bearing, w, dir).
        """
        return max(v_air_mps - wind_mps, 1.0)

    def takeoff_time_s(self, h_agl_m: float) -> float:
        """T_to = h / v_vert."""
        return h_agl_m / max(self.p.v_vert_mps, 0.5)

    def landing_time_s(self, h_agl_m: float) -> float:
        """T_ld = h / v_vert (симметрично взлёту)."""
        return self.takeoff_time_s(h_agl_m)

    def takeoff_energy_wh(self, h_agl_m: float) -> float:
        """Энергия на взлёте.

        На висении P = k_h·m (v = 0, k_v·v³ = 0).
        Ветер на мощность не влияет (модель организаторов).
        """
        t_s = self.takeoff_time_s(h_agl_m)
        p_w = self.p.k_h * self.p.mass_kg
        return p_w * t_s / 3600.0

    def landing_energy_wh(self, h_agl_m: float) -> float:
        """Энергия на посадке = энергии взлёта (симметрия)."""
        return self.takeoff_energy_wh(h_agl_m)