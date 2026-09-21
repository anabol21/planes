"""Runtime, не точка интеграции.

Stages around ``solver.solve``: ingest, bind, compile, judge, emit.
``compile`` checks that ``scenario`` is a JSON object and stores it unchanged.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from planes.runtime.logs import redact
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
        _stage("ingest", "не разобрал запрос, это не JSON")
        raise ValueError("request is not JSON") from exc
    try:
        request = parse_request(data)
    except ValueError:
        _stage("ingest", "не разобрал запрос")
        raise
    _stage("ingest", "разобрал ComputeRequest v0")
    return request


def bind(request: ComputeRequest) -> BoundInputs:
    bound = BoundInputs(
        job_id=request.job_id,
        scenario=request.scenario,
        objective=request.optimization.objective,
        seed=request.seed,
        time_limit_seconds=request.optimization.time_limit_seconds,
    )
    _stage("bind", f"связал поля запроса, job_id={bound.job_id}")
    return bound


def compile(bound: BoundInputs) -> Problem:  # noqa: A001
    if not isinstance(bound.scenario, dict):
        _stage("compile", f"scenario не объект, job_id={bound.job_id}")
        raise ValueError("scenario must be a JSON object")
    problem = Problem(
        job_id=bound.job_id,
        scenario=bound.scenario,
        objective=bound.objective,
        seed=bound.seed,
        time_limit_seconds=bound.time_limit_seconds,
    )
    _stage("compile", f"сохранил scenario как объект, job_id={problem.job_id}")
    return problem


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
    text = dump_response(response)
    _stage("emit", f"собрал JSON ответа, job_id={response.job_id}")
    return text


def run(raw: bytes, solve_fn: SolveFn | None = None) -> ComputeResponse:
    try:
        request = ingest(raw)
    except ValueError as exc:
        return _judged(_input_error(raw, str(exc)))
    try:
        problem = compile(bind(request))
    except ValueError as exc:
        return _judged(_input_error(raw, str(exc)))
    started = time.monotonic()
    deadline = started + float(problem.time_limit_seconds)
    _stage("solve", f"вызываю solver.solve, job_id={problem.job_id}")
    try:
        result = (solve_fn or default_solve)(problem, deadline)
    except NotImplementedError:
        _stage("solve", f"NotImplementedError, job_id={problem.job_id}")
        return _judged(_error(problem, [_NOT_IMPLEMENTED], time.monotonic() - started))
    except Exception:
        _stage("solve", f"исключение, job_id={problem.job_id}")
        return _judged(
            _error(problem, ["solver failed before producing a result"], time.monotonic() - started)
        )
    _stage("solve", f"результат {type(result).__name__}, job_id={problem.job_id}")
    return _judged(judge(problem, result, time.monotonic() - started))


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


def _judged(response: ComputeResponse) -> ComputeResponse:
    _stage("judge", f"исход {response.outcome}, job_id={response.job_id}")
    return response


def _stage(name: str, message: str) -> None:
    sys.stderr.write(redact(f"[{name}] {message}") + "\n")


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
