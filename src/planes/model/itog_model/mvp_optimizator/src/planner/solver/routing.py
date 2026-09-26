"""OR-Tools routing для одного борта.

Модель: узлы = полоса; расстояние = exit_i → entry_j (bidirectional через reverse).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from planner.models import Swath, VPP
from planner.physics.base import PhysicsModel, PhysicsParams


@dataclass
class RoutingResult:
    uav_id: str
    swath_ids: list[str]
    T_air_s: float
    T_total_s: float
    E_wh: float
    vpp_id: str
    h_agl_m: float


def _scale(v: float, k: int = 1000) -> int:
    return int(round(v * k))


def solve_routing_for_uav(
    uav_id: str,
    swaths: list[Swath],
    vpp: VPP,
    t_ij: np.ndarray,
    e_ij: np.ndarray,
    t_survey: np.ndarray,
    physics: PhysicsModel,
    params: PhysicsParams,
    h_agl_m: float,
    time_limit_s: float = 10.0,
) -> RoutingResult | None:
    m = len(swaths)
    if m == 0:
        return RoutingResult(
            uav_id=uav_id, swath_ids=[],
            T_air_s=0.0, T_total_s=0.0, E_wh=0.0,
            vpp_id=vpp.id, h_agl_m=h_agl_m,
        )

    n_nodes = m + 1

    T_to = physics.takeoff_time_s(h_agl_m)
    T_ld = physics.landing_time_s(h_agl_m)
    E_to = physics.takeoff_energy_wh(h_agl_m)
    E_ld = physics.landing_energy_wh(h_agl_m)

    T_budget = params.T_max_s * (1.0 - params.reserve_fraction) - T_to - T_ld
    E_budget = params.E_batt_wh * (1.0 - params.reserve_fraction) - E_to - E_ld

    if T_budget <= 0 or E_budget <= 0:
        return None

    manager = pywrapcp.RoutingIndexManager(n_nodes, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    # --- Время ---
    def time_callback(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        t = t_ij[i, j]
        if j > 0:
            t += t_survey[j]
        return _scale(t)

    t_cb = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(t_cb)
    routing.AddDimension(t_cb, 0, _scale(T_budget), True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    # --- Энергия ---
    def energy_callback(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        return _scale(e_ij[i, j])

    e_cb = routing.RegisterTransitCallback(energy_callback)
    routing.AddDimension(e_cb, 0, _scale(E_budget), True, "Energy")
    energy_dim = routing.GetDimensionOrDie("Energy")

    # --- Поиск ---
    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    sp.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    sp.time_limit.FromSeconds(int(time_limit_s))

    solution = routing.SolveWithParameters(sp)
    if solution is None:
        return None

    # --- Разбор ---
    idx = routing.Start(0)
    order: list[str] = []
    T_used = 0
    E_used = 0

    while not routing.IsEnd(idx):
        nxt = solution.Value(routing.NextVar(idx))
        T_used += routing.GetArcCostForVehicle(idx, nxt, 0)
        E_used += (
            solution.Value(energy_dim.CumulVar(nxt))
            - solution.Value(energy_dim.CumulVar(idx))
        )
        node = manager.IndexToNode(nxt)
        if node > 0:
            order.append(swaths[node - 1].id)
        idx = nxt

    T_air_s = T_used / 1000.0
    E_wh = E_used / 1000.0

    return RoutingResult(
        uav_id=uav_id,
        swath_ids=order,
        T_air_s=T_air_s,
        T_total_s=T_air_s + T_to + T_ld,
        E_wh=E_wh + E_to + E_ld,
        vpp_id=vpp.id,
        h_agl_m=h_agl_m,
    )