"""Provisional backend-local v0 structures.

These types support the RUS-001 prototype. They are not the final shared domain
contract and must not be imported as such by other workstreams.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping


CONTRACT_VERSION = "v0"
EngineOutcome = Literal["feasible", "infeasible", "timed_out", "error"]


def freeze_json(value: Any) -> Any:
    """Return a recursively immutable representation of JSON-compatible data."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    """Return ordinary JSON-serializable containers from frozen data."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ComputeRequest:
    """Input passed through the backend-owned OptimizationEngine port."""

    job_id: str
    scenario: Mapping[str, Any]
    optimization: Mapping[str, Any]
    seed: int
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract version: {self.contract_version}")
        object.__setattr__(self, "scenario", freeze_json(self.scenario))
        object.__setattr__(self, "optimization", freeze_json(self.optimization))


@dataclass(frozen=True, slots=True)
class ComputeResponse:
    """Structured terminal response returned by an OptimizationEngine."""

    job_id: str
    outcome: EngineOutcome
    solver_report: Mapping[str, Any]
    mission_plan: Mapping[str, Any] | None = None
    artifacts: tuple[Any, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract version: {self.contract_version}")
        if self.outcome not in {"feasible", "infeasible", "timed_out", "error"}:
            raise ValueError(f"unsupported engine outcome: {self.outcome}")
        if self.outcome != "feasible" and self.mission_plan is not None:
            raise ValueError("mission_plan is only valid for a feasible outcome")
        object.__setattr__(self, "solver_report", freeze_json(self.solver_report))
        if self.mission_plan is not None:
            object.__setattr__(self, "mission_plan", freeze_json(self.mission_plan))
        object.__setattr__(self, "artifacts", tuple(freeze_json(item) for item in self.artifacts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "job_id": self.job_id,
            "outcome": self.outcome,
            "mission_plan": thaw_json(self.mission_plan),
            "solver_report": thaw_json(self.solver_report),
            "artifacts": thaw_json(self.artifacts),
        }
