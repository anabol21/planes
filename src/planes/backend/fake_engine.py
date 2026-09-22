"""Deterministic test/development implementation of the engine port."""

from __future__ import annotations

from .models import ComputeRequest, ComputeResponse


class FakeOptimizationEngine:
    """Produce synthetic outcomes selected by optimization.test_outcome.

    This fake performs no UAV routing or optimization. It exists only to exercise
    backend lifecycle behavior while the runtime adapter is unavailable.
    """

    _OUTCOMES = {"feasible", "infeasible", "timed_out", "error"}

    def solve(self, request: ComputeRequest) -> ComputeResponse:
        outcome = request.optimization.get("test_outcome", "feasible")
        if outcome not in self._OUTCOMES:
            raise ValueError(f"unsupported fake test_outcome: {outcome!r}")
        if outcome == "error":
            raise RuntimeError("simulated FakeOptimizationEngine failure")

        report = {
            "method": "fake_backend_lifecycle_only",
            "runtime_seconds": 0.0,
            "seed": request.seed,
            "limitations": ["synthetic test data; no UAV optimization performed"],
        }
        if outcome == "feasible":
            return ComputeResponse(
                job_id=request.job_id,
                outcome="feasible",
                mission_plan={
                    "test_data": True,
                    "sorties": [
                        {
                            "sortie_id": "FAKE-SORTIE-001",
                            "waypoints": [],
                            "note": "synthetic lifecycle fixture; not flyable",
                        }
                    ],
                },
                solver_report=report,
            )
        return ComputeResponse(
            job_id=request.job_id,
            outcome=outcome,
            solver_report=report,
        )
