"""Worker orchestration and a separate-process command line entry point."""

from __future__ import annotations

import argparse
from typing import Any

from .engine import OptimizationEngine
from .fake_engine import FakeOptimizationEngine
from .models import ComputeRequest
from .runtime_engine import RuntimeOptimizationEngine
from .store import SQLiteJobStore


class Worker:
    def __init__(self, store: SQLiteJobStore, engine: OptimizationEngine) -> None:
        self.store = store
        self.engine = engine

    def run_once(self) -> str | None:
        job = self.store.claim_next_queued_job()
        if job is None:
            return None
        try:
            request = ComputeRequest(
                contract_version=job.contract_version,
                job_id=job.job_id,
                scenario=job.scenario,
                optimization=job.optimization,
                seed=job.seed,
            )
            response = self.engine.solve(request)
            self.store.finish_with_response(job.job_id, response)
        except Exception as error:
            self.store.mark_failed(job.job_id, self._error_payload(error))
        return job.job_id

    @staticmethod
    def _error_payload(error: Exception) -> dict[str, Any]:
        return {
            "type": type(error).__name__,
            "message": str(error),
            "source": "worker",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RUS-001 backend worker claim")
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument(
        "--engine",
        choices=("fake", "runtime"),
        default="fake",
        help="optimization engine composition (default: fake)",
    )
    args = parser.parse_args()
    engine: OptimizationEngine
    if args.engine == "runtime":
        engine = RuntimeOptimizationEngine()
    else:
        engine = FakeOptimizationEngine()
    worker = Worker(SQLiteJobStore(args.database), engine)
    worker.run_once()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a process
    raise SystemExit(main())
