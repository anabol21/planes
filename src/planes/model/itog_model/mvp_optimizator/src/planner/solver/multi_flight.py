"""Разбиение полос борта на несколько вылетов (с учётом зарядки)."""

from __future__ import annotations

from planner.models import Swath, VPP
from planner.physics.base import PhysicsModel, PhysicsParams
from planner.solver.matrices import build_time_energy_matrices
from planner.solver.routing import RoutingResult, solve_routing_for_uav


def solve_multi_flight(
    uav_id: str,
    swaths: list[Swath],
    vpp: VPP,
    fwd,
    physics: PhysicsModel,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
    h_agl_m: float,
    R_max: int,
) -> list[RoutingResult]:
    """
    Пытается уложить полосы в один вылет. Если не влезают — режет на несколько.
    """
    results: list[RoutingResult] = []
    remaining = list(swaths)

    for flight_idx in range(R_max):
        if not remaining:
            break

        t_ij, e_ij, t_survey = build_time_energy_matrices(
            swaths=remaining,
            vpp=vpp,
            fwd=fwd,
            physics=physics,
            params=params,
            wind_speed_mps=wind_speed_mps,
            wind_direction_deg=wind_direction_deg,
        )

        res = solve_routing_for_uav(
            uav_id=uav_id,
            swaths=remaining,
            vpp=vpp,
            t_ij=t_ij,
            e_ij=e_ij,
            t_survey=t_survey,
            physics=physics,
            params=params,
            h_agl_m=h_agl_m,
        )

        if res is None or not res.swath_ids:
            break

        results.append(res)
        done = set(res.swath_ids)
        remaining = [s for s in remaining if s.id not in done]

    return results