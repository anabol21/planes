"""Backend-owned conversion wrapper for the runtime engine adapter."""

from __future__ import annotations

from typing import Protocol, cast

from planes.contracts import parse_optimization_v0, parse_scenario_v0
from planes.runtime.adapter import RuntimeEngineAdapter
from planes.runtime.types import (
    ComputeRequest as RuntimeComputeRequest,
    ComputeResponse as RuntimeComputeResponse,
    parse_request,
    response_to_dict,
)

from .models import (
    ComputeRequest,
    ComputeResponse,
    EngineOutcome,
    thaw_json,
)


class RuntimeAdapter(Protocol):
    """Narrow injectable surface implemented by RuntimeEngineAdapter."""

    def solve(self, request: RuntimeComputeRequest) -> RuntimeComputeResponse:
        ...


class RuntimeOptimizationEngine:
    """Adapt backend-local v0 models to the runtime-owned v0 adapter."""

    def __init__(self, adapter: RuntimeAdapter | None = None) -> None:
        self.adapter = adapter if adapter is not None else RuntimeEngineAdapter()

    def solve(self, request: ComputeRequest) -> ComputeResponse:
        runtime_request = self._to_runtime_request(request)
        runtime_response = self.adapter.solve(runtime_request)
        return self._to_backend_response(runtime_response)

    @staticmethod
    def _to_runtime_request(request: ComputeRequest) -> RuntimeComputeRequest:
        scenario = thaw_json(request.scenario)
        optimization = thaw_json(request.optimization)
        parsed_scenario = parse_scenario_v0(scenario)
        parsed_optimization = parse_optimization_v0(optimization)
        return parse_request(
            {
                "contract_version": request.contract_version,
                "job_id": request.job_id,
                "scenario": parsed_scenario.to_dict(),
                "optimization": parsed_optimization.to_dict(),
                "seed": request.seed,
            }
        )

    @staticmethod
    def _to_backend_response(response: RuntimeComputeResponse) -> ComputeResponse:
        body = response_to_dict(response)
        return ComputeResponse(
            contract_version=body["contract_version"],
            job_id=body["job_id"],
            outcome=cast(EngineOutcome, body["outcome"]),
            mission_plan=body.get("mission_plan"),
            solver_report=body["solver_report"],
            artifacts=tuple(body["artifacts"]),
        )
