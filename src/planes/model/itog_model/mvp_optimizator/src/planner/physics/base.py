"""Интерфейс модели полёта.

Модель мощности мультиротора:
    P = k_h·m + k_v·v³

Влияние ветра на мощность НЕ моделируется (согласно указаниям
организаторов). Ветер влияет только на время перелёта через
V_ground = v_air + w (см. planner.utils.wind.ground_speed_mps).

Запас на маневрирование и погоду — reserve_fraction = 0.15.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PhysicsParams:
    """Всё, что нужно физике для одного борта."""

    # --- обязательные ---
    uav_id: str
    model: str
    mass_kg: float
    v_air_mps: float
    v_vert_mps: float
    v_survey_mps: float
    E_batt_wh: float
    T_max_s: float

    # --- опциональные ---
    v_stall_mps: float = 0.0
    v_climb_mps: float = 3.0       # набор высоты при перелёте
    v_descent_mps: float = 3.0     # сброс высоты
    v_min_mps: float = 1.0         # минимальная горизонтальная

    # Коэффициенты модели мощности мультиротора.
    # k_w удалён — ветер на мощность не влияет.
    k_h: float = 90.0              # Вт/кг (весовая составляющая)
    k_v: float = 0.02              # Вт·с³/м³ (паразитное сопротивление)

    t_turn_s: float = 5.0
    reserve_fraction: float = 0.15   # было 0.05 → 0.15
    T_catapult_s: float = 0.0
    T_parachute_s: float = 0.0
    P_const_w: float = 0.0
    T_charge_s: float = 0.0


class PhysicsModel(ABC):
    """Абстрактная модель полёта."""

    @abstractmethod
    def power_w(self, v_air_mps: float, wind_mps: float) -> float: ...

    @abstractmethod
    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float: ...

    @abstractmethod
    def takeoff_time_s(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def landing_time_s(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def takeoff_energy_wh(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def landing_energy_wh(self, h_agl_m: float) -> float: ...