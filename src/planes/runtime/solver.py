"""Для агента Гриши.

``solve`` is the only solver hook. The pipeline around it already runs.
The listener accepts only the geo envelope. It does not call gibrid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from planes.runtime.enumeration import is_outer_scenario


@dataclass(frozen=True)
class Problem:
    job_id: str
    scenario: dict[str, Any]
    objective: str
    seed: int
    time_limit_seconds: int | float


@dataclass(frozen=True)
class Solution:
    mission_plan: dict[str, Any]
    method: str
    objective_value: float
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class Infeasible:
    """A solver outcome. This is not an infrastructure failure."""

    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimedOut:
    limitations: tuple[str, ...] = ()


_SCENARIO_FIELDS = (
    "takeoff",
    "uav",
    "area",
    "gsd_cm_per_px",
    "criterion",
    "camera",
    "survey",
    "wind",
    "power_coeffs",
)
_ASSEMBLED = ("routes", "strips", "validation", "mission")
_NOT_GLOBALLY_OPTIMAL = "heuristic result is not globally optimal"
_TIME_LIMIT = "solver stopped at the time limit"
_GEO_ONLY = "the listener only accepts the geo envelope"


def solve(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Solve one geo envelope.

    An envelope with ``aerodromes`` and ``boards`` calls
    ``grisha_f2c_bridge.solve_via_isolated_grisha_f2c`` (isolated F2C
    generateBestSwaths / auto-angle; strip_direction_deg ignored) when
    ``PLANES_SOLVE_BACKEND`` is unset or ``grisha_f2c_iso``. Rollback via
    ``PLANES_SOLVE_BACKEND=legacy_fields2cover`` calls
    ``geo_mission.solve_envelope``. An envelope that still has ``pads`` or
    ``uav_types`` is rejected. A one-card ``takeoff`` + ``uav`` scenario,
    and any other scenario that is not that envelope, raises ``ValueError``
    before any gibrid import. The message says the listener only accepts
    the geo envelope. The pipeline turns that into ``outcome=error``.

    ``deadline`` is ``time.monotonic()`` plus the problem time limit. The
    geo envelope observes it. This function does not call ``run``,
    ``run_optimizer``, ``solve_milp``, or ``solve_metaheuristic``.
    """
    if isinstance(problem.scenario, dict) and "uav_types" in problem.scenario:
        raise ValueError("uav_types is not accepted")
    if isinstance(problem.scenario, dict) and "pads" in problem.scenario:
        raise ValueError("pads is not accepted")
    if is_outer_scenario(problem.scenario):
        return _solve_outer(problem, deadline)
    raise ValueError(_GEO_ONLY)


def _solve_outer(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Live Grisha+F2C contour: isolated worker, generateBestSwaths.

    Falls back to legacy ``geo_mission.solve_envelope`` only when env
    ``PLANES_SOLVE_BACKEND=legacy_fields2cover`` is set (rollback).
    This is pack/split F2C, not full mvp LNS/assignment.
    """
    import os

    backend = os.environ.get("PLANES_SOLVE_BACKEND", "grisha_f2c_iso").strip().lower()
    if backend in ("legacy", "legacy_fields2cover", "geo_mission"):
        from planes.runtime.geo_mission import solve_envelope

        return solve_envelope(problem, deadline)
    from planes.runtime.grisha_f2c_bridge import solve_via_isolated_grisha_f2c

    return solve_via_isolated_grisha_f2c(problem, deadline)


def _map_result(result: dict[str, Any]) -> Solution | Infeasible | TimedOut:
    status = result.get("status")
    if status in ("optimal", "feasible"):
        return _solution(result, ())
    if status == "heuristic":
        return _solution(result, (_NOT_GLOBALLY_OPTIMAL,))
    if status == "infeasible":
        reason = result.get("reason")
        limitations = (str(reason),) if isinstance(reason, str) and reason else ()
        return Infeasible(limitations)
    if status == "unknown":
        reason = result.get("reason")
        limitations = (_TIME_LIMIT,)
        if isinstance(reason, str) and reason:
            limitations = (*limitations, reason)
        return TimedOut(limitations)
    raise ValueError(f"unexpected solver status: {status}")


def _solution(result: dict[str, Any], limitations: tuple[str, ...]) -> Solution:
    missing = [name for name in _ASSEMBLED if name not in result]
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    mission = result["mission"]
    criterion = result.get("criterion")
    if criterion == "min_time":
        objective_value = float(mission["mission_time_s"])
    elif criterion == "min_flight_hours":
        objective_value = float(mission["total_flight_time_s"])
    else:
        raise ValueError("missing fields: criterion")
    method = result.get("solver")
    if not isinstance(method, str) or not method:
        raise ValueError("missing fields: solver")
    return Solution(
        mission_plan=result,
        method=method,
        objective_value=objective_value,
        limitations=limitations,
    )
