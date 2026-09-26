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
    spectrum_mismatch_limitation,
)
from planes.runtime.logs import record


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

    An envelope with ``aerodromes`` and ``boards`` enumerates one core call
    per runnable board card and returns the single best successful call.
    An envelope that still has ``pads`` or ``uav_types`` is rejected. A
    scenario that still has one ``takeoff`` and one ``uav`` stays on that
    one-call path.

    ``deadline`` is ``time.monotonic()`` plus the problem time limit.
    Missing fields and pydantic or import failures raise ``ValueError``.
    The pipeline turns that into ``outcome=error``.

    The core call uses Grisha's metaheuristic (``solver_choice="meta"``).
    A single takeoff/uav scenario keeps his ``SolverCfg`` turn fields.
    The outer path takes ``turn_time_s`` from the catalog model and leaves
    ``apply_turn_to_base`` false. Only ``time_limit_s`` is the task limit.
    Non-passport values are written into limitations and the process log.
    """
    if isinstance(problem.scenario, dict) and "uav_types" in problem.scenario:
        raise ValueError("uav_types is not accepted")
    if isinstance(problem.scenario, dict) and "pads" in problem.scenario:
        raise ValueError("pads is not accepted")
    if is_outer_scenario(problem.scenario):
        return _solve_outer(problem, deadline)
    payload = _scenario_payload(problem.scenario)
    payload["solver"] = _solver_cfg(problem.time_limit_seconds, problem.scenario.get("solver"))
    run_optimizer, data = _load_input(payload)
    if time.monotonic() >= deadline:
        return TimedOut((_TIME_LIMIT,))
    # A finished optimal, feasible, or heuristic result stands. ``unknown`` is
    # the solver stop without a solution, including a time-limit stop.
    # The process kill outside this function remains the backstop when the
    # metaheuristic does not observe ``time_limit_s``.
    return _map_result(run_optimizer(data, "meta", seed=problem.seed))


def _solve_outer(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Enumerate admitted board cards and return the single best successful call."""
    if time.monotonic() >= deadline:
        lines = (_TIME_LIMIT,)
        _log_outer(problem.job_id, lines)
        return TimedOut(lines)
    outcome = run_candidates(
        problem.scenario,
        seed=problem.seed,
        time_limit_s=problem.time_limit_seconds,
        deadline=deadline,
    )
    criterion = problem.scenario.get("criterion")
    if not isinstance(criterion, str):
        raise ValueError("missing fields: criterion")
    noted = (
        *tuple(skip_limitation(skip) for skip in outcome.skips),
        *tuple(spectrum_mismatch_limitation(item) for item in outcome.mismatches),
        *outcome.disclosures,
    )
    winner = select_winner(outcome.attempts, criterion)
    if winner is not None:
        mapped = _map_result(winner.result)
        if isinstance(mapped, Solution):
            lines = (
                *mapped.limitations,
                f"winning aerodrome id: {winner.aerodrome_id}",
                f"winning board id: {winner.board_id}",
                f"winning model id: {winner.model_id}",
                f"winning camera id: {winner.camera_id}",
                *noted,
            )
            _log_outer(problem.job_id, lines)
            return Solution(
                mission_plan=mapped.mission_plan,
                method=mapped.method,
                objective_value=mapped.objective_value,
                limitations=lines,
            )
        lines = (*mapped.limitations, *noted)
        _log_outer(problem.job_id, lines)
        if isinstance(mapped, Infeasible):
            return Infeasible(lines)
        return TimedOut(lines)
    if outcome.stopped_for_deadline or any(
        item.result.get("status") == "unknown" for item in outcome.attempts
    ):
        lines = (_TIME_LIMIT, *noted)
        _log_outer(problem.job_id, lines)
        return TimedOut(lines)
    reasons: list[str] = []
    if not outcome.attempts:
        reasons.append(outcome.reason or "no runnable board")
    for item in outcome.attempts:
        reason = item.result.get("reason")
        if isinstance(reason, str) and reason and reason not in reasons:
            reasons.append(reason)
    for line in noted:
        if line not in reasons:
            reasons.append(line)
    lines = tuple(reasons)
    _log_outer(problem.job_id, lines)
    return Infeasible(lines)


def _log_outer(job_id: str, lines: tuple[str, ...]) -> None:
    """Write limitation lines to the job process log, including when ``run()`` was not called."""
    body = "\n".join(lines) if lines else "outer enumeration: no limitation lines"
    record(job_id, f"job_id={job_id} outer-limitations\n{body}")


def _solver_cfg(time_limit_s: int | float, existing: Any) -> dict[str, Any]:
    """Task time limit, plus Grisha's other ``SolverCfg`` fields when he sent them."""
    block: dict[str, Any] = {}
    if isinstance(existing, dict):
        for key in ("turn_time_s", "apply_turn_to_base"):
            if key in existing:
                block[key] = existing[key]
    block["time_limit_s"] = time_limit_s
    return block


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
