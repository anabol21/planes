"""Runtime, не точка интеграции.

Stages around ``solver.solve``: ingest, bind, compile, judge, emit.
``compile`` checks that ``scenario`` is a JSON object and stores it unchanged.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from planes.runtime.solver import Infeasible, Problem, Solution, TimedOut
from planes.runtime.solver import solve as default_solve
from planes.runtime.types import (
    ComputeRequest,
    ComputeResponse,
    dump_response,
    make_response,
    parse_request,
    safe_job_id,
)

SolveFn = Callable[[Problem, float], Solution | Infeasible | TimedOut]
_NOT_IMPLEMENTED = "solver body is not implemented"


@dataclass(frozen=True)
class BoundInputs:
    job_id: str
    scenario: Any
    objective: str
    seed: int
    time_limit_seconds: int | float


def ingest(raw: bytes) -> ComputeRequest:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request is not JSON") from exc
    return parse_request(data)


def bind(request: ComputeRequest) -> BoundInputs:
    return BoundInputs(
        job_id=request.job_id,
        scenario=request.scenario,
        objective=request.optimization.objective,
        seed=request.seed,
        time_limit_seconds=request.optimization.time_limit_seconds,
    )


def compile(bound: BoundInputs) -> Problem:  # noqa: A001
    if not isinstance(bound.scenario, dict):
        raise ValueError("scenario must be a JSON object")
    return Problem(
        job_id=bound.job_id,
        scenario=bound.scenario,
        objective=bound.objective,
        seed=bound.seed,
        time_limit_seconds=bound.time_limit_seconds,
    )


def judge(problem: Problem, result: object, runtime_seconds: float) -> ComputeResponse:
    if isinstance(result, Solution):
        if not isinstance(result.mission_plan, dict) or not result.method:
            return _error(problem, ["solver returned a malformed Solution"], runtime_seconds)
        return make_response(
            job_id=problem.job_id,
            outcome="feasible",
            method=result.method,
            objective=problem.objective,
            runtime_seconds=runtime_seconds,
            seed=problem.seed,
            limitations=list(result.limitations),
            mission_plan=result.mission_plan,
        )
    if isinstance(result, Infeasible):
        return make_response(
            job_id=problem.job_id,
            outcome="infeasible",
            method="runtime-pipeline",
            objective=problem.objective,
            runtime_seconds=runtime_seconds,
            seed=problem.seed,
            limitations=list(result.limitations),
        )
    if isinstance(result, TimedOut):
        return make_response(
            job_id=problem.job_id,
            outcome="timed_out",
            method="runtime-pipeline",
            objective=problem.objective,
            runtime_seconds=runtime_seconds,
            seed=problem.seed,
            limitations=list(result.limitations),
        )
    return _error(problem, ["solver returned an unexpected result"], runtime_seconds)


def emit(response: ComputeResponse) -> str:
    return dump_response(response)


def run(raw: bytes, solve_fn: SolveFn | None = None) -> ComputeResponse:
    try:
        problem = compile(bind(ingest(raw)))
    except ValueError as exc:
        return _input_error(raw, str(exc))
    started = time.monotonic()
    deadline = started + float(problem.time_limit_seconds)
    try:
        result = (solve_fn or default_solve)(problem, deadline)
    except NotImplementedError:
        return _error(problem, [_NOT_IMPLEMENTED], time.monotonic() - started)
    except Exception:
        return _error(problem, ["solver failed before producing a result"], time.monotonic() - started)
    return judge(problem, result, time.monotonic() - started)


def _error(problem: Problem, limitations: list[str], runtime_seconds: float) -> ComputeResponse:
    return make_response(
        job_id=problem.job_id,
        outcome="error",
        method="runtime-pipeline",
        objective=problem.objective,
        runtime_seconds=runtime_seconds,
        seed=problem.seed,
        limitations=limitations,
    )


def _input_error(raw: bytes, message: str) -> ComputeResponse:
    job_id = "unknown"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        job_id = safe_job_id(data.get("job_id"))
    return make_response(
        job_id=job_id,
        outcome="error",
        method="runtime-pipeline",
        objective="",
        runtime_seconds=0.0,
        seed=0,
        limitations=[message],
    )
