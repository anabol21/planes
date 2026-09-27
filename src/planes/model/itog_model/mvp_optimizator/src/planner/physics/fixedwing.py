"""Fixed-wing: Geoscan 201 (v2)."""

from __future__ import annotations

from planner.physics.base import PhysicsModel, PhysicsParams


class FixedWingPhysics(PhysicsModel):
    """Упрощение для MVP: P = const."""

    def __init__(self, p: PhysicsParams):
        self.p = p

    def power_w(self, v_air_mps: float, wind_mps: float) -> float:
        return self.p.P_const_w

    def ground_speed_mps(self, v_air_mps: float, wind_mps: float) -> float:
        return max(v_air_mps - wind_mps, self.p.v_stall_mps)

    def takeoff_time_s(self, h_agl_m: float) -> float:
        return self.p.T_catapult_s + h_agl_m / max(self.p.v_vert_mps, 1.0)

    def landing_time_s(self, h_agl_m: float) -> float:
        return self.p.T_parachute_s + h_agl_m / max(self.p.v_vert_mps, 1.0)

    def takeoff_energy_wh(self, h_agl_m: float) -> float:
        return 0.0  # катапульта — внешняя

    def landing_energy_wh(self, h_agl_m: float) -> float:
        return 0.0  # парашют — механика