from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planes.backend.api import BackendAPI
from planes.backend.fake_engine import FakeOptimizationEngine
from planes.backend.service import BackendService, ResultNotReadyError
from planes.backend.store import SQLiteJobStore
from planes.backend.worker import Worker


class BackendPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = (
            Path(__file__).resolve().parent / f".test-jobs-{uuid.uuid4().hex}.sqlite3"
        )
        self.database = str(self.database_path)
        self.store = SQLiteJobStore(self.database)
        self.service = BackendService(self.store)

    def tearDown(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def submit(self, outcome: str = "feasible") -> dict[str, Any]:
        return self.service.submit_job(
            scenario={"name": "test scenario", "crs": "EPSG:4326"},
            optimization={"test_outcome": outcome, "limit_seconds": 1},
            seed=17,
        )

    def test_happy_lifecycle_and_submission_is_asynchronous(self) -> None:
        submitted = self.submit()
        self.assertEqual("queued", submitted["state"])
        with self.assertRaises(ResultNotReadyError):
            self.service.get_result(submitted["job_id"])

        observed_states: list[str] = []

        class ObservingEngine(FakeOptimizationEngine):
            def solve(inner_self, request):  # type: ignore[no-untyped-def]
                observed_states.append(self.service.get_job(request.job_id)["state"])
                return super().solve(request)

        claimed = Worker(self.store, ObservingEngine()).run_once()

        self.assertEqual(submitted["job_id"], claimed)
        self.assertEqual(["running"], observed_states)
        self.assertEqual("completed", self.service.get_job(claimed)["state"])
        result = self.service.get_result(claimed)
        self.assertEqual("feasible", result["outcome"])
        self.assertTrue(result["mission_plan"]["test_data"])

    def test_atomic_claim_allows_exactly_one_winner(self) -> None:
        submitted = self.submit()
        barrier = threading.Barrier(2)
        claims: list[str | None] = []
        claims_lock = threading.Lock()

        def claim() -> None:
            contender = SQLiteJobStore(self.database)
            barrier.wait()
            result = contender.claim_next_queued_job()
            with claims_lock:
                claims.append(result.job_id if result else None)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(1, claims.count(submitted["job_id"]))
        self.assertEqual(1, claims.count(None))

    def test_infeasible_is_completed(self) -> None:
        job_id = self.submit("infeasible")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        self.assertEqual("completed", self.service.get_job(job_id)["state"])
        self.assertEqual("infeasible", self.service.get_result(job_id)["outcome"])

    def test_timeout_has_distinct_terminal_state(self) -> None:
        job_id = self.submit("timed_out")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        self.assertEqual("timed_out", self.service.get_job(job_id)["state"])
        self.assertEqual("timed_out", self.service.get_result(job_id)["outcome"])

    def test_engine_error_is_failed_and_never_success(self) -> None:
        job_id = self.submit("error")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        self.assertEqual("failed", self.service.get_job(job_id)["state"])
        result = self.service.get_result(job_id)
        self.assertEqual("failed", result["state"])
        self.assertEqual("RuntimeError", result["error"]["type"])

    def test_submission_stores_immutable_serialized_snapshots(self) -> None:
        scenario = {"name": "original", "nested": {"value": 1}}
        optimization = {"test_outcome": "feasible", "weights": [1, 2]}
        job_id = self.service.submit_job(
            scenario=scenario, optimization=optimization, seed=9
        )["job_id"]

        scenario["name"] = "mutated"
        scenario["nested"]["value"] = 999
        optimization["weights"].append(3)

        stored = self.store.get_job(job_id)
        self.assertIsNotNone(stored)
        self.assertEqual("original", stored.scenario["name"])
        self.assertEqual(1, stored.scenario["nested"]["value"])
        self.assertEqual([1, 2], stored.optimization["weights"])

    def test_http_adapter_exposes_submit_status_and_result(self) -> None:
        api = BackendAPI(self.service)
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "job_submission_v0.json"
        submission_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        status, submitted = self.call_api(
            api,
            "POST",
            "/jobs",
            submission_fixture,
        )
        self.assertEqual("202 Accepted", status)
        job_id = submitted["job_id"]

        status, job = self.call_api(api, "GET", f"/jobs/{job_id}")
        self.assertEqual("200 OK", status)
        self.assertEqual("queued", job["state"])

        Worker(self.store, FakeOptimizationEngine()).run_once()
        status, result = self.call_api(api, "GET", f"/jobs/{job_id}/result")
        self.assertEqual("200 OK", status)
        self.assertEqual("feasible", result["outcome"])

    def test_malformed_json_returns_400(self) -> None:
        status, response = self.call_raw_api(BackendAPI(self.service), "POST", "/jobs", b"{")
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_request", response["error"])

    def test_missing_scenario_returns_400(self) -> None:
        status, response = self.call_api(
            BackendAPI(self.service),
            "POST",
            "/jobs",
            {"contract_version": "v0", "optimization": {}, "seed": 1},
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_request", response["error"])

    def test_unsupported_contract_version_returns_400(self) -> None:
        status, response = self.call_api(
            BackendAPI(self.service),
            "POST",
            "/jobs",
            {
                "contract_version": "v1",
                "scenario": {"name": "test"},
                "optimization": {},
                "seed": 1,
            },
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_request", response["error"])

    def test_non_integer_seed_returns_400(self) -> None:
        status, response = self.call_api(
            BackendAPI(self.service),
            "POST",
            "/jobs",
            {
                "scenario": {"name": "test"},
                "optimization": {},
                "seed": "1",
            },
        )
        self.assertEqual("400 Bad Request", status)
        self.assertEqual("invalid_request", response["error"])

    def test_unknown_job_status_and_result_return_404(self) -> None:
        api = BackendAPI(self.service)
        for path in ("/jobs/unknown", "/jobs/unknown/result"):
            with self.subTest(path=path):
                status, response = self.call_api(api, "GET", path)
                self.assertEqual("404 Not Found", status)
                self.assertEqual("job_not_found", response["error"])

    def test_result_before_terminal_returns_409(self) -> None:
        job_id = self.submit()["job_id"]
        status, response = self.call_api(
            BackendAPI(self.service), "GET", f"/jobs/{job_id}/result"
        )
        self.assertEqual("409 Conflict", status)
        self.assertEqual("result_not_ready", response["error"])
        self.assertEqual("queued", response["state"])

    def test_http_infeasible_result_is_completed(self) -> None:
        job_id = self.submit("infeasible")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        status, result = self.call_api(
            BackendAPI(self.service), "GET", f"/jobs/{job_id}/result"
        )
        self.assertEqual("200 OK", status)
        self.assertEqual("completed", result["state"])
        self.assertEqual("infeasible", result["outcome"])

    def test_http_timeout_result_has_distinct_state(self) -> None:
        job_id = self.submit("timed_out")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        status, result = self.call_api(
            BackendAPI(self.service), "GET", f"/jobs/{job_id}/result"
        )
        self.assertEqual("200 OK", status)
        self.assertEqual("timed_out", result["state"])
        self.assertEqual("timed_out", result["outcome"])

    def test_http_failed_result_contains_structured_error(self) -> None:
        job_id = self.submit("error")["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        status, result = self.call_api(
            BackendAPI(self.service), "GET", f"/jobs/{job_id}/result"
        )
        self.assertEqual("200 OK", status)
        self.assertEqual("failed", result["state"])
        self.assertEqual("RuntimeError", result["error"]["type"])
        self.assertEqual("worker", result["error"]["source"])

    def test_unsupported_method_on_recognized_route_returns_405(self) -> None:
        status, response = self.call_api(BackendAPI(self.service), "PUT", "/jobs")
        self.assertEqual("405 Method Not Allowed", status)
        self.assertEqual("method_not_allowed", response["error"])

    def test_unknown_path_returns_404(self) -> None:
        status, response = self.call_api(BackendAPI(self.service), "GET", "/unknown")
        self.assertEqual("404 Not Found", status)
        self.assertEqual("not_found", response["error"])

    def test_socket_bound_api_submit_and_status(self) -> None:
        class QuietHandler(WSGIRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = make_server(
            "127.0.0.1",
            0,
            BackendAPI(self.service),
            handler_class=QuietHandler,
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        payload = {
            "scenario": {"name": "socket smoke", "crs": "EPSG:4326"},
            "optimization": {"test_outcome": "feasible"},
            "seed": 5,
        }
        try:
            request = Request(
                f"{base_url}/jobs",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                self.assertEqual(202, response.status)
                submitted = json.load(response)

            with urlopen(f"{base_url}/jobs/{submitted['job_id']}", timeout=5) as response:
                self.assertEqual(200, response.status)
                status = json.load(response)
            self.assertEqual("queued", status["state"])
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
        self.assertFalse(server_thread.is_alive())

    def test_worker_cli_processes_job_in_separate_process(self) -> None:
        job_id = self.submit()["job_id"]
        source_root = str(Path(__file__).resolve().parents[2] / "src")
        environment = {**os.environ, "PYTHONPATH": source_root}

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "planes.backend.worker",
                "--database",
                self.database,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("completed", self.service.get_job(job_id)["state"])
        self.assertEqual("feasible", self.service.get_result(job_id)["outcome"])

    @staticmethod
    def call_api(
        api: BackendAPI,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        return BackendPipelineTests.call_raw_api(api, method, path, body)

    @staticmethod
    def call_raw_api(
        api: BackendAPI,
        method: str,
        path: str,
        body: bytes = b"",
    ) -> tuple[str, dict[str, Any]]:
        captured: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        response_body = b"".join(api(environ, start_response))
        return captured["status"], json.loads(response_body)


if __name__ == "__main__":
    unittest.main()
