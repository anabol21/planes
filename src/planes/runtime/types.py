"""Local v0 dataclasses aligned with docs/architecture/INTERFACES_V0.md.

These types are a runtime copy for this checkpoint. They are not the shared
contract package. Field names match the interface note and must not drift.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "v0"
OUTCOMES = frozenset({"feasible", "infeasible", "timed_out", "error"})
PLACEHOLDER_OUTCOMES = frozenset({"feasible", "infeasible", "crash", "invalid", "sleep"})
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class OptimizationSettings:
    """Solver limits taken from a ComputeRequest.

    ``placeholder_outcome`` is a harness switch read only by the placeholder
    core. It is not part of the product request and a later solver binary
    should ignore it. Allowed values: feasible (default), infeasible, crash,
    invalid, sleep.
    """

    objective: str
    time_limit_seconds: int | float
    placeholder_outcome: str | None = None


@dataclass(frozen=True)
class ComputeRequest:
    contract_version: str
    job_id: str
    scenario: dict[str, Any]
    optimization: OptimizationSettings
    seed: int


@dataclass(frozen=True)
class SolverReport:
    method: str
    objective: str
    runtime_seconds: float
    seed: int
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    ref: str


@dataclass(frozen=True)
class ComputeResponse:
    contract_version: str
    job_id: str
    outcome: str
    solver_report: SolverReport
    artifacts: tuple[ArtifactRef, ...]
    mission_plan: dict[str, Any] | None = None


def parse_request(data: Any) -> ComputeRequest:
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")
    if data.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("contract_version must be v0")
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise ValueError("job_id is missing or unsafe")
    scenario = data.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be a JSON object")
    return ComputeRequest(
        contract_version=CONTRACT_VERSION,
        job_id=job_id,
        scenario=dict(scenario),
        optimization=_parse_optimization(data.get("optimization")),
        seed=_parse_seed(data.get("seed")),
    )


def parse_request_bytes(raw: bytes) -> ComputeRequest:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request is not JSON") from exc
    return parse_request(data)


def request_to_dict(request: ComputeRequest) -> dict[str, Any]:
    optimization: dict[str, Any] = {
        "objective": request.optimization.objective,
        "time_limit_seconds": request.optimization.time_limit_seconds,
    }
    if request.optimization.placeholder_outcome is not None:
        optimization["placeholder_outcome"] = request.optimization.placeholder_outcome
    return {
        "contract_version": request.contract_version,
        "job_id": request.job_id,
        "scenario": request.scenario,
        "optimization": optimization,
        "seed": request.seed,
    }


def parse_response(data: Any) -> ComputeResponse:
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    if data.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("response contract_version must be v0")
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
        raise ValueError("response job_id is missing or unsafe")
    outcome = data.get("outcome")
    if outcome not in OUTCOMES:
        raise ValueError("response outcome is not allowed")
    mission = data.get("mission_plan") if "mission_plan" in data else None
    if mission is not None and not isinstance(mission, dict):
        raise ValueError("mission_plan must be a JSON object when present")
    return ComputeResponse(
        contract_version=CONTRACT_VERSION,
        job_id=job_id,
        outcome=outcome,
        mission_plan=dict(mission) if mission is not None else None,
        solver_report=_parse_report(data.get("solver_report")),
        artifacts=_parse_artifacts(data.get("artifacts")),
    )


def response_to_dict(response: ComputeResponse) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contract_version": response.contract_version,
        "job_id": response.job_id,
        "outcome": response.outcome,
        "solver_report": {
            "method": response.solver_report.method,
            "objective": response.solver_report.objective,
            "runtime_seconds": response.solver_report.runtime_seconds,
            "seed": response.solver_report.seed,
            "limitations": list(response.solver_report.limitations),
        },
        "artifacts": [{"kind": item.kind, "ref": item.ref} for item in response.artifacts],
    }
    if response.mission_plan is not None:
        body["mission_plan"] = response.mission_plan
    return body


def dump_response(response: ComputeResponse) -> str:
    return json.dumps(response_to_dict(response), ensure_ascii=False) + "\n"


def make_response(
    *,
    job_id: str,
    outcome: str,
    method: str,
    objective: str,
    runtime_seconds: float,
    seed: int,
    limitations: list[str],
    log_ref: str | None = None,
    mission_plan: dict[str, Any] | None = None,
) -> ComputeResponse:
    if outcome not in OUTCOMES:
        raise ValueError("outcome is not allowed")
    artifacts: list[ArtifactRef] = []
    if log_ref:
        artifacts.append(ArtifactRef(kind="log", ref=log_ref))
    elapsed = runtime_seconds if math.isfinite(runtime_seconds) and runtime_seconds >= 0 else 0.0
    return ComputeResponse(
        contract_version=CONTRACT_VERSION,
        job_id=job_id if _JOB_ID.fullmatch(job_id) else "unknown",
        outcome=outcome,
        mission_plan=mission_plan,
        solver_report=SolverReport(
            method=method,
            objective=objective,
            runtime_seconds=elapsed,
            seed=seed,
            limitations=tuple(limitations),
        ),
        artifacts=tuple(artifacts),
    )


def safe_job_id(value: Any) -> str:
    if isinstance(value, str) and _JOB_ID.fullmatch(value):
        return value
    return "unknown"


def _parse_optimization(value: Any) -> OptimizationSettings:
    if not isinstance(value, dict):
        raise ValueError("optimization must be a JSON object")
    objective = value.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("optimization.objective must be a non-empty string")
    limit = value.get("time_limit_seconds")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        raise ValueError("optimization.time_limit_seconds must be a number of seconds")
    if isinstance(limit, float) and not math.isfinite(limit):
        raise ValueError("optimization.time_limit_seconds must be finite")
    if limit < 0:
        raise ValueError("optimization.time_limit_seconds must be non-negative")
    placeholder = value.get("placeholder_outcome")
    if placeholder is not None and not isinstance(placeholder, str):
        raise ValueError("optimization.placeholder_outcome must be a string")
    stored_limit: int | float = limit if isinstance(limit, int) else float(limit)
    return OptimizationSettings(
        objective=objective,
        time_limit_seconds=stored_limit,
        placeholder_outcome=placeholder,
    )


def _parse_seed(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("seed must be an integer")
    return value


def _parse_report(value: Any) -> SolverReport:
    if not isinstance(value, dict):
        raise ValueError("solver_report must be a JSON object")
    method = value.get("method")
    objective = value.get("objective")
    runtime = value.get("runtime_seconds")
    seed = value.get("seed")
    limitations = value.get("limitations")
    if not isinstance(method, str) or not method:
        raise ValueError("solver_report.method must be a non-empty string")
    if not isinstance(objective, str):
        raise ValueError("solver_report.objective must be a string")
    if isinstance(runtime, bool) or not isinstance(runtime, (int, float)):
        raise ValueError("solver_report.runtime_seconds must be a number of seconds")
    if isinstance(runtime, float) and not math.isfinite(runtime):
        raise ValueError("solver_report.runtime_seconds must be finite")
    if runtime < 0:
        raise ValueError("solver_report.runtime_seconds must be non-negative")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("solver_report.seed must be an integer")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise ValueError("solver_report.limitations must be a list of strings")
    return SolverReport(
        method=method,
        objective=objective,
        runtime_seconds=float(runtime),
        seed=seed,
        limitations=tuple(limitations),
    )


def _parse_artifacts(value: Any) -> tuple[ArtifactRef, ...]:
    if not isinstance(value, list):
        raise ValueError("artifacts must be a list")
    items: list[ArtifactRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("artifact must be a JSON object")
        kind = item.get("kind")
        ref = item.get("ref")
        if not isinstance(kind, str) or not isinstance(ref, str):
            raise ValueError("artifact kind and ref must be strings")
        items.append(ArtifactRef(kind=kind, ref=ref))
    return tuple(items)
