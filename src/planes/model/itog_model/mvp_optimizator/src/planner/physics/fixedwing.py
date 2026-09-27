"""Fixed-wing: Geoscan 201 (v2).

Отличия от мультиротора:
  - нет висения: взлёт — катапульта + набор высоты, посадка — парашют;
  - разворот — вираж с радиусом R, не на месте;
  - ограничение по скорости сваливания: нельзя лететь медленнее v_stall;
  - мощность считается не по rotor-формуле, а как константа / аэродинамика.
"""

from __future__ import annotations

from planner.physics.base import PhysicsModel, PhysicsParams


class FixedWingPhysics(PhysicsModel):
    """Упрощение для MVP: P = const (или fallback на среднюю мощность)."""

    def __init__(self, p: PhysicsParams):
        self.p = p

    # --------------------------------------------------
    # Мощность
    # --------------------------------------------------

    def power_w(self, v_air_mps: float, wind_mps: float) -> float:
        """Крейсерская мощность.

        Приоритет:
          1. P_const_w, если задана (> 0).
          2. Fallback: E_batt / T_max — средняя мощность за весь полёт.

        v_air_mps и wind_mps в этой модели игнорируются — упрощение MVP.
        """
        if self.p.P_const_w > 0:
            return self.p.P_const_w

        if self.p.T_max_s > 0:
            return self.p.E_batt_wh / (self.p.T_max_s / 3600.0)

        return 0.0

    # --------------------------------------------------
    # Скорость
    # --------------------------------------------------

    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float:
        """Worst-case путевая скорость: полёт строго против ветра.

        Возвращает v_air - |w| без clamp'а к v_stall. Если результат меньше
        v_stall — борт физически не может лететь в этом направлении, см.
        is_wind_feasible().

        Для маршрутизации с учётом направления ветра используется
        planner.utils.wind.ground_speed_mps(v_air, bearing, w, wind_dir).
        Этот метод — только для worst-case оценок (валидатор, тесты).
        """
        return v_air_mps - wind_mps

    def is_wind_feasible(self, wind_mps: float) -> bool:
        """True, если борт может лететь против ветра данной силы.

        Условие: v_air - |w| >= v_stall.
        """
        if self.p.v_stall_mps <= 0:
            return True
        return (self.p.v_air_mps - wind_mps) >= self.p.v_stall_mps

    # --------------------------------------------------
    # Взлёт / посадка
    # --------------------------------------------------

    def takeoff_time_s(self, h_agl_m: float) -> float:
        """T_to = T_catapult + h / v_climb.

        Катапульта — внешний запуск, время фиксированное.
        Набор высоты — по v_climb_mps (а не v_vert_mps: у fixed-wing
        нет вертикальной скорости висения).
        """
        v_climb = max(self.p.v_climb_mps, 0.5)
        return self.p.T_catapult_s + h_agl_m / v_climb

    def landing_time_s(self, h_agl_m: float) -> float:
        """T_ld = h / v_descend + T_parachute.

        Спуск — по v_descent_mps, парашют — фиксированное время.
        """
        v_descent = max(self.p.v_descent_mps, 0.5)
        return h_agl_m / v_descent + self.p.T_parachute_s

    def takeoff_energy_wh(self, h_agl_m: float) -> float:
        """Энергия АКБ на взлёте = 0: катапульта — внешняя механика."""
        return 0.0

    def landing_energy_wh(self, h_agl_m: float) -> float:
        """Энергия АКБ на посадке = 0: парашют — механика."""
        return 0.0