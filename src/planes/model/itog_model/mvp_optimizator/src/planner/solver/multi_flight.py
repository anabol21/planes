"""Разбиение полос борта на несколько вылетов."""

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
    wind_mps: float,
    h_agl_m: float,
    R_max: int,
) -> list[RoutingResult]:
    """
    Пытается уложить все полосы в один вылет.
    Если не помещаются — режет на несколько вылетов.
    """
    results: list[RoutingResult] = []
    remaining = list(swaths)

    for _ in range(R_max):
        if not remaining:
            break

        t_ij, e_ij, t_survey = build_time_energy_matrices(
            swaths=remaining,
            vpp=vpp,
            fwd=fwd,
            physics=physics,
            params=params,
            wind_mps=wind_mps,
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