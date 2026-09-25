"""Worker orchestration and a separate-process command line entry point."""

from __future__ import annotations

import argparse
import signal
import time
from collections.abc import Callable
from typing import Any

from .engine import OptimizationEngine
from .fake_engine import FakeOptimizationEngine
from .models import ComputeRequest
from .runtime_engine import RuntimeOptimizationEngine
from .store import SQLiteJobStore

EMPTY_QUEUE_POLL_SECONDS = 0.5


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

    def run_loop(
        self,
        *,
        sleep: Callable[[float], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        poll_interval_s: float = EMPTY_QUEUE_POLL_SECONDS,
    ) -> None:
        """Claim and run one queued job at a time until asked to stop.

        An empty queue waits ``poll_interval_s`` and then polls again. The
        current job finishes before the stop flag is observed.
        """
        if sleep is None:
            sleep = time.sleep
        if should_stop is None:
            should_stop = install_stop_signal_handlers()
        while not should_stop():
            if self.run_once() is None and not should_stop():
                sleep(poll_interval_s)

    @staticmethod
    def _error_payload(error: Exception) -> dict[str, Any]:
        return {
            "type": type(error).__name__,
            "message": str(error),
            "source": "worker",
        }


def install_stop_signal_handlers() -> Callable[[], bool]:
    """Return a flag that becomes true after SIGINT or SIGTERM."""
    requested = False

    def _request_stop(signum: int, _frame: object) -> None:
        nonlocal requested
        requested = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    return lambda: requested


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RUS-001 backend worker")
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument(
        "--engine",
        choices=("fake", "runtime"),
        default="fake",
        help="optimization engine composition (default: fake)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="keep claiming queued jobs until SIGINT or SIGTERM (default: one job)",
    )
    args = parser.parse_args()
    engine: OptimizationEngine
    if args.engine == "runtime":
        engine = RuntimeOptimizationEngine()
    else:
        engine = FakeOptimizationEngine()
    worker = Worker(SQLiteJobStore(args.database), engine)
    if args.loop:
        worker.run_loop()
    else:
        worker.run_once()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a process
    raise SystemExit(main())
