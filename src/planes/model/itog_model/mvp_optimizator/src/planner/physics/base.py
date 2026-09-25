"""Интерфейс модели полёта."""

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
    k_h: float = 90.0
    k_v: float = 0.02
    k_w: float = 0.008
    t_turn_s: float = 5.0
    reserve_fraction: float = 0.05
    T_catapult_s: float = 0.0
    T_parachute_s: float = 0.0
    P_const_w: float = 0.0

    # NEW: время зарядки АКБ (сек)
    T_charge_s: float = 0.0


class PhysicsModel(ABC):
    """Абстрактная модель полёта."""

    @abstractmethod
    def power_w(self, v_air_mps: float, wind_mps: float) -> float:
        """Мощность в ваттах."""

    @abstractmethod
    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float:
        """Модуль путевой скорости."""

    @abstractmethod
    def takeoff_time_s(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def landing_time_s(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def takeoff_energy_wh(self, h_agl_m: float) -> float: ...

    @abstractmethod
    def landing_energy_wh(self, h_agl_m: float) -> float: ...