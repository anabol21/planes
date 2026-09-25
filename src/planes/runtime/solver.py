"""Для агента Гриши.

``solve`` is the only solver hook. The pipeline around it already runs.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planes.runtime.enumeration import (
    is_outer_scenario,
    run_candidates,
    select_winner,
    skip_limitation,
)


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
_GIBRID_ROOT = (
    Path(__file__).resolve().parents[1] / "model" / "basic_model" / "gibrid-optimizer"
)

_optimizer: tuple[Any, Any, Any] | None = None


def solve(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Build one ``InputData`` and call ``run``.

    An envelope with ``pads`` and ``required_spectrum`` enumerates admitted
    catalog triples and returns the single best successful call. An envelope
    that still has ``uav_types`` is rejected. A scenario that still has one
    ``takeoff`` and one ``uav`` stays on that one-call path.

    ``deadline`` is ``time.monotonic()`` plus the problem time limit.
    Missing fields and pydantic or import failures raise ``ValueError``.
    The pipeline turns that into ``outcome=error``.
    """
    if isinstance(problem.scenario, dict) and "uav_types" in problem.scenario:
        raise ValueError("uav_types is not accepted")
    if is_outer_scenario(problem.scenario):
        return _solve_outer(problem, deadline)
    payload = _scenario_payload(problem.scenario)
    payload["solver"] = {"time_limit_s": problem.time_limit_seconds}
    run_optimizer, data = _load_input(payload)
    if time.monotonic() >= deadline:
        return TimedOut((_TIME_LIMIT,))
    # A finished optimal, feasible, or heuristic result stands. ``unknown`` is
    # the solver stop without a solution, including a time-limit stop.
    # The process kill outside this function remains the backstop when the
    # metaheuristic does not observe ``time_limit_s``.
    return _map_result(run_optimizer(data, seed=problem.seed))


def _solve_outer(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Enumerate admitted triples and return the single best successful call."""
    if time.monotonic() >= deadline:
        return TimedOut((_TIME_LIMIT,))
    outcome = run_candidates(
        problem.scenario,
        seed=problem.seed,
        time_limit_s=problem.time_limit_seconds,
        deadline=deadline,
    )
    criterion = problem.scenario.get("criterion")
    if not isinstance(criterion, str):
        raise ValueError("missing fields: criterion")
    noted = tuple(skip_limitation(skip) for skip in outcome.skips)
    winner = select_winner(outcome.attempts, criterion)
    if winner is not None:
        mapped = _map_result(winner.result)
        if not isinstance(mapped, Solution):
            return mapped
        return Solution(
            mission_plan=mapped.mission_plan,
            method=mapped.method,
            objective_value=mapped.objective_value,
            limitations=(
                *mapped.limitations,
                f"winning pad id: {winner.pad_id}",
                f"winning model id: {winner.model_id}",
                f"winning camera id: {winner.camera_id}",
                *noted,
            ),
        )
    if outcome.stopped_for_deadline or any(
        item.result.get("status") == "unknown" for item in outcome.attempts
    ):
        return TimedOut((_TIME_LIMIT, *noted))
    reasons: list[str] = []
    if not outcome.attempts:
        reasons.append(outcome.reason or "no runnable uav and camera for spectrum")
    for item in outcome.attempts:
        reason = item.result.get("reason")
        if isinstance(reason, str) and reason and reason not in reasons:
            reasons.append(reason)
    for line in noted:
        if line not in reasons:
            reasons.append(line)
    return Infeasible(tuple(reasons))


def _scenario_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scenario, dict):
        raise ValueError("missing fields: scenario")
    missing = [name for name in _SCENARIO_FIELDS if name not in scenario]
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    return {name: scenario[name] for name in _SCENARIO_FIELDS}


def _load_input(payload: dict[str, Any]) -> tuple[Any, Any]:
    run_optimizer, input_data_cls, validation_error = _optimizer_api()
    try:
        data = input_data_cls(**payload)
    except validation_error as exc:
        raise ValueError(_invalid_fields(exc)) from exc
    return run_optimizer, data


def _optimizer_api() -> tuple[Any, Any, Any]:
    global _optimizer
    if _optimizer is not None:
        return _optimizer
    root = str(_GIBRID_ROOT)
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        from optimizer.main import run as run_optimizer
        from optimizer.models import InputData
        from pydantic import ValidationError
    except ImportError as exc:
        raise ValueError(f"optimizer import failed: {exc}") from exc
    finally:
        if inserted and root in sys.path:
            sys.path.remove(root)
    _optimizer = (run_optimizer, InputData, ValidationError)
    return _optimizer


def _invalid_fields(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    seen: list[str] = []
    if callable(errors):
        for err in errors():
            loc = ".".join(str(part) for part in err.get("loc", ()))
            if loc and loc not in seen:
                seen.append(loc)
    if not seen:
        seen.append("scenario")
    return "missing fields: " + ", ".join(seen)


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
