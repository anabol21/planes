from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from typing import cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planes.backend.models import ComputeRequest
from planes.backend.runtime_engine import RuntimeAdapter, RuntimeOptimizationEngine
from planes.backend.service import BackendService
from planes.backend.store import SQLiteJobStore
from planes.backend.worker import Worker, main
from planes.runtime.types import (
    ComputeRequest as RuntimeComputeRequest,
    ComputeResponse as RuntimeComputeResponse,
    make_response,
)


class StubRuntimeAdapter:
    def __init__(
        self,
        response: RuntimeComputeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[RuntimeComputeRequest] = []

    def solve(self, request: RuntimeComputeRequest) -> RuntimeComputeResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("stub response was not configured")
        return self.response


def runtime_response(
    job_id: str,
    outcome: str,
    *,
    log_ref: str | None = None,
) -> RuntimeComputeResponse:
    mission_plan = {"sorties": [{"sortie_id": "runtime-1"}]} if outcome == "feasible" else None
    return make_response(
        job_id=job_id,
        outcome=outcome,
        method="runtime-test-stub",
        objective="min_time",
        runtime_seconds=0.25,
        seed=17,
        limitations=[],
        log_ref=log_ref,
        mission_plan=mission_plan,
    )


class RuntimeEngineConversionTests(unittest.TestCase):
    def request(self, **optimization: object) -> ComputeRequest:
        return ComputeRequest(
            contract_version="v0",
            job_id="job-runtime-001",
            scenario={"name": "runtime scenario", "nested": {"value": 1}},
            optimization=optimization,
            seed=17,
        )

    def test_exact_backend_request_conversion_uses_runtime_types(self) -> None:
        adapter = StubRuntimeAdapter(runtime_response("job-runtime-001", "feasible"))
        engine = RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))

        engine.solve(
            self.request(
                objective="min_time",
                time_limit_seconds=30,
                test_outcome="infeasible",
                ignored_backend_setting=True,
            )
        )

        self.assertEqual(1, len(adapter.requests))
        converted = adapter.requests[0]
        self.assertIsInstance(converted, RuntimeComputeRequest)
        self.assertEqual("v0", converted.contract_version)
        self.assertEqual("job-runtime-001", converted.job_id)
        self.assertEqual(
            {"name": "runtime scenario", "nested": {"value": 1}}, converted.scenario
        )
        self.assertEqual("min_time", converted.optimization.objective)
        self.assertEqual(30, converted.optimization.time_limit_seconds)
        self.assertIsNone(converted.optimization.placeholder_outcome)
        self.assertEqual(17, converted.seed)

    def test_conversion_ignores_fake_only_optimization_fields(self) -> None:
        adapter = StubRuntimeAdapter(runtime_response("job-runtime-001", "infeasible"))
        engine = RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))

        engine.solve(
            self.request(
                objective="min_total_flight_time",
                time_limit_seconds=0,
                test_outcome="feasible",
            )
        )

        converted = adapter.requests[0]
        self.assertFalse(hasattr(converted.optimization, "test_outcome"))
        self.assertEqual("min_total_flight_time", converted.optimization.objective)

    def test_runtime_artifact_references_survive_response_conversion(self) -> None:
        adapter = StubRuntimeAdapter(
            runtime_response("job-runtime-001", "feasible", log_ref="runtime://logs/job-1")
        )
        engine = RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))

        response = engine.solve(self.request(objective="min_time", time_limit_seconds=30))

        self.assertEqual(
            [{"kind": "log", "ref": "runtime://logs/job-1"}],
            response.to_dict()["artifacts"],
        )


class RuntimeWorkerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = (
            Path(__file__).resolve().parent / f".test-runtime-{uuid.uuid4().hex}.sqlite3"
        )
        self.store = SQLiteJobStore(self.database_path)
        self.service = BackendService(self.store)

    def tearDown(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def submit(self, optimization: dict[str, object] | None = None) -> str:
        return self.service.submit_job(
            scenario={"name": "runtime lifecycle", "crs": "EPSG:4326"},
            optimization=optimization
            if optimization is not None
            else {"objective": "min_time", "time_limit_seconds": 30},
            seed=17,
        )["job_id"]

    def run_response(self, outcome: str) -> tuple[str, StubRuntimeAdapter]:
        job_id = self.submit()
        adapter = StubRuntimeAdapter(runtime_response(job_id, outcome))
        Worker(
            self.store, RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))
        ).run_once()
        return job_id, adapter

    def test_invalid_runtime_settings_fail_without_calling_adapter(self) -> None:
        job_id = self.submit({"test_outcome": "feasible"})
        adapter = StubRuntimeAdapter()

        Worker(
            self.store, RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))
        ).run_once()

        self.assertEqual([], adapter.requests)
        self.assertEqual("failed", self.service.get_job(job_id)["state"])
        error = self.service.get_result(job_id)["error"]
        self.assertEqual("ValueError", error["type"])
        self.assertIn("optimization.objective", error["message"])
        self.assertEqual("worker", error["source"])

    def test_feasible_runtime_response_completes_job(self) -> None:
        job_id, _ = self.run_response("feasible")
        result = self.service.get_result(job_id)
        self.assertEqual("completed", result["state"])
        self.assertEqual("feasible", result["outcome"])
        self.assertEqual("runtime-1", result["mission_plan"]["sorties"][0]["sortie_id"])

    def test_infeasible_runtime_response_completes_job(self) -> None:
        job_id, _ = self.run_response("infeasible")
        result = self.service.get_result(job_id)
        self.assertEqual("completed", result["state"])
        self.assertEqual("infeasible", result["outcome"])

    def test_timed_out_runtime_response_remains_distinct(self) -> None:
        job_id, _ = self.run_response("timed_out")
        result = self.service.get_result(job_id)
        self.assertEqual("timed_out", result["state"])
        self.assertEqual("timed_out", result["outcome"])

    def test_runtime_error_response_fails_job(self) -> None:
        job_id, _ = self.run_response("error")
        result = self.service.get_result(job_id)
        self.assertEqual("failed", result["state"])
        self.assertEqual("error", result["error"]["outcome"])
        self.assertEqual("runtime-test-stub", result["error"]["solver_report"]["method"])

    def test_missing_runtime_configuration_fails_without_http(self) -> None:
        job_id = self.submit()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("planes.runtime.adapter.urllib.request.build_opener") as build_opener,
        ):
            Worker(self.store, RuntimeOptimizationEngine()).run_once()

        build_opener.assert_not_called()
        result = self.service.get_result(job_id)
        self.assertEqual("failed", result["state"])
        self.assertEqual("error", result["error"]["outcome"])
        limitations = result["error"]["solver_report"]["limitations"]
        self.assertIn("Missing compute configuration", limitations[0])
        self.assertNotIn("COMPUTE_TOKEN=", str(result))

    def test_runtime_adapter_exception_fails_job(self) -> None:
        job_id = self.submit()
        adapter = StubRuntimeAdapter(error=RuntimeError("stub adapter failed"))

        Worker(
            self.store, RuntimeOptimizationEngine(cast(RuntimeAdapter, adapter))
        ).run_once()

        result = self.service.get_result(job_id)
        self.assertEqual("failed", result["state"])
        self.assertEqual("RuntimeError", result["error"]["type"])
        self.assertEqual("stub adapter failed", result["error"]["message"])


class WorkerEngineSelectionTests(unittest.TestCase):
    def test_fake_engine_remains_cli_default(self) -> None:
        database = Path(__file__).resolve().parent / f".test-cli-{uuid.uuid4().hex}.sqlite3"
        try:
            with (
                patch.object(sys, "argv", ["worker", "--database", str(database)]),
                patch("planes.backend.worker.Worker") as worker_class,
            ):
                self.assertEqual(0, main())
            engine = worker_class.call_args.args[1]
            self.assertEqual("FakeOptimizationEngine", type(engine).__name__)
            worker_class.return_value.run_once.assert_called_once_with()
        finally:
            database.unlink(missing_ok=True)

    def test_explicit_runtime_engine_selects_runtime_wrapper(self) -> None:
        database = Path(__file__).resolve().parent / f".test-cli-{uuid.uuid4().hex}.sqlite3"
        try:
            with (
                patch.object(
                    sys,
                    "argv",
                    ["worker", "--database", str(database), "--engine", "runtime"],
                ),
                patch("planes.backend.worker.RuntimeOptimizationEngine") as runtime_class,
                patch("planes.backend.worker.Worker") as worker_class,
            ):
                self.assertEqual(0, main())
            runtime_class.assert_called_once_with()
            self.assertIs(runtime_class.return_value, worker_class.call_args.args[1])
            worker_class.return_value.run_once.assert_called_once_with()
        finally:
            database.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
