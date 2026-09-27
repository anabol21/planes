"""Мультиротор: Gemini, Geoscan 801."""

from __future__ import annotations

from planner.physics.base import PhysicsModel, PhysicsParams


class RotorPhysics(PhysicsModel):
    """P = k_h·m + k_v·v³ + k_w·|w|²·m."""

    def __init__(self, p: PhysicsParams):
        self.p = p

    def power_w(self, v_air_mps: float, wind_mps: float) -> float:
        p = self.p
        return (
            p.k_h * p.mass_kg
            + p.k_v * (v_air_mps ** 3)
            + p.k_w * (wind_mps ** 2) * p.mass_kg
        )

    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float:
        # Худший случай: летим против ветра
        return max(v_air_mps - wind_mps, 1.0)

    def takeoff_time_s(self, h_agl_m: float) -> float:
        return h_agl_m / self.p.v_vert_mps

    def landing_time_s(self, h_agl_m: float) -> float:
        return self.takeoff_time_s(h_agl_m)

    def takeoff_energy_wh(self, h_agl_m: float) -> float:
        t_s = self.takeoff_time_s(h_agl_m)
        # мощность на взлёте = k_h·m (без аэродинамики)
        p_w = self.p.k_h * self.p.mass_kg
        return p_w * t_s / 3600.0

    def landing_energy_wh(self, h_agl_m: float) -> float:
        return self.takeoff_energy_wh(h_agl_m)