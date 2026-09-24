"""Сборка маршрутов, waypoints и разбивки по этапам.

Общий модуль для MILP и метаэвристики: обе ветки возвращают
routes_raw в формате [{"uav_id": int, "nodes": [1, 2, ...]}, ...].
"""

from typing import Any, Dict, List

from .models import InputData


def build_routes(
    result: Dict[str, Any],
    pre: Dict[str, Any],
    strips: List,
    input_data: InputData,
) -> List[Dict[str, Any]]:
    if result.get("status") not in ("optimal", "feasible", "heuristic"):
        return []

    entries = pre["entries"]
    exits = pre["exits"]
    t_pure = pre["t_pure"]
    t = pre["t"]
    tau = pre["tau"]
    eps = pre["eps"]
    T_takeoff = pre["T_takeoff"]
    T_landing = pre["T_landing"]
    E_takeoff = pre["E_takeoff"]
    E_landing = pre["E_landing"]
    P_const = pre["P_const"]

    routes_out: List[Dict[str, Any]] = []

    for route in result["routes_raw"]:
        nodes = [0] + route["nodes"] + [0]

        waypoints: List[Dict[str, Any]] = []
        base_lat, base_lon = entries[0]
        waypoints.append({"type": "takeoff", "lat": base_lat, "lon": base_lon})

        transit_time = 0.0
        turn_time_total = 0.0
        transit_energy = 0.0
        turns_energy = 0.0

        for k in range(len(nodes) - 1):
            i = nodes[k]
            j = nodes[k + 1]

            dt_pure = t_pure[i, j]
            dt_turn = t[i, j] - t_pure[i, j]

            transit_time += dt_pure
            turn_time_total += dt_turn
            transit_energy += P_const * dt_pure / 3600.0
            turns_energy += P_const * dt_turn / 3600.0

            if j == 0:
                lat_e, lon_e = exits[0]
                waypoints.append(
                    {"type": "landing", "lat": lat_e, "lon": lon_e}
                )
            else:
                lat_s, lon_s = entries[j]
                lat_e, lon_e = exits[j]
                waypoints.append({
                    "type": "strip_start", "strip": j - 1,
                    "lat": lat_s, "lon": lon_s,
                })
                waypoints.append({
                    "type": "strip_end", "strip": j - 1,
                    "lat": lat_e, "lon": lon_e,
                })

        strip_ids = [n - 1 for n in route["nodes"]]
        survey_time = sum(tau[s] for s in strip_ids)
        survey_energy = sum(eps[s] for s in strip_ids)

        total_time = (
            T_takeoff + transit_time + turn_time_total + survey_time + T_landing
        )
        total_energy = (
            E_takeoff + transit_energy + turns_energy + survey_energy + E_landing
        )

        routes_out.append({
            "uav_id": route["uav_id"],
            "strips": strip_ids,
            "waypoints": waypoints,
            "time_breakdown_s": {
                "takeoff": T_takeoff,
                "transit": transit_time,
                "turns": turn_time_total,
                "survey": survey_time,
                "landing": T_landing,
                "total": total_time,
            },
            "energy_breakdown_wh": {
                "takeoff": E_takeoff,
                "transit": transit_energy,
                "turns": turns_energy,
                "survey": survey_energy,
                "landing": E_landing,
                "total": total_energy,
            },
        })

    return routes_out