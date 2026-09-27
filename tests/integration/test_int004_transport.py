"""INT-004 golden scenario from backend HTTP through runtime HTTP parsing."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from planes.backend.api import BackendAPI
from planes.backend.runtime_engine import RuntimeOptimizationEngine
from planes.backend.service import BackendService
from planes.backend.store import SQLiteJobStore
from planes.backend.worker import Worker
from planes.contracts import ScenarioV0
from planes.runtime.http_server import ComputeHTTPServer, ComputeHandler
from planes.runtime.types import ComputeRequest, dump_response, make_response

GOLDEN = REPO / "tests" / "fixtures" / "scenario_v0_full.json"
TOKEN = "int004-deterministic-test-token"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


class _MemoryLock:
    def try_acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass


class InputToRuntimeTransportTest(unittest.TestCase):
    def test_golden_scenario_reaches_runtime_parser_without_field_loss(self) -> None:
        submission = json.loads(GOLDEN.read_text(encoding="utf-8"))
        captured: list[tuple[ComputeRequest, ScenarioV0, dict[str, Any]]] = []

        def capture(
            request: ComputeRequest, scenario: ScenarioV0, body: bytes
        ) -> bytes:
            captured.append((request, scenario, json.loads(body.decode("utf-8"))))
            response = make_response(
                job_id=request.job_id,
                outcome="feasible",
                method="int004-capture-solver",
                objective=request.optimization.objective,
                runtime_seconds=0.0,
                seed=request.seed,
                limitations=["capture solver; optimizer not invoked"],
                mission_plan={"captured_scenario_id": scenario["scenario_id"]},
            )
            return dump_response(response).encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="planes-int004-") as directory:
            store = SQLiteJobStore(Path(directory) / "jobs.sqlite3")
            service = BackendService(store)
            backend = make_server(
                "127.0.0.1", 0, BackendAPI(service), handler_class=_QuietHandler
            )
            backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
            with patch.dict(os.environ, {"COMPUTE_TOKEN": TOKEN}, clear=False):
                runtime = ComputeHTTPServer(
                    ("127.0.0.1", 8080),
                    ComputeHandler,
                    request_executor=capture,
                    lock_factory=_MemoryLock,
                )
            runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
            backend_thread.start()
            runtime_thread.start()
            try:
                api_request = Request(
                    f"http://127.0.0.1:{backend.server_port}/jobs",
                    data=json.dumps(submission).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(api_request, timeout=5) as response:
                    self.assertEqual(202, response.status)
                    status = json.load(response)
                self.assertEqual("queued", status["state"])

                stored = store.get_job(status["job_id"])
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(submission["scenario"], stored.scenario)
                self.assertEqual(submission["optimization"], stored.optimization)
                self.assertEqual(submission["seed"], stored.seed)

                with patch.dict(
                    os.environ,
                    {
                        "COMPUTE_HOST": "127.0.0.1",
                        "COMPUTE_TOKEN": TOKEN,
                        "COMPUTE_TIMEOUT_SECONDS": "5",
                    },
                    clear=False,
                ):
                    self.assertEqual(
                        status["job_id"],
                        Worker(store, RuntimeOptimizationEngine()).run_once(),
                    )

                self.assertEqual(1, len(captured))
                runtime_request, parsed_scenario, wire = captured[0]
                self.assertIsInstance(parsed_scenario, ScenarioV0)
                self.assertEqual(submission["scenario"], parsed_scenario.to_dict())
                self.assertEqual(submission["scenario"], wire["scenario"])
                self.assertEqual(submission["optimization"], wire["optimization"])
                self.assertEqual(submission["seed"], runtime_request.seed)
                self.assertEqual(2, len(parsed_scenario["survey_areas"]))
                self.assertEqual(1, len(parsed_scenario["restricted_zones"]))
                self.assertEqual(2, len(parsed_scenario["obstacles"]))
                self.assertEqual(2, len(parsed_scenario["aerodromes"]))
                self.assertEqual(2, len(parsed_scenario["board_cards"]))

                terminal = service.get_result(status["job_id"])
                self.assertEqual("completed", terminal["state"])
                self.assertEqual("feasible", terminal["outcome"])
                self.assertEqual(
                    "scenario-v0-full",
                    terminal["mission_plan"]["captured_scenario_id"],
                )
            finally:
                backend.shutdown()
                runtime.shutdown()
                backend.server_close()
                runtime.server_close()
                backend_thread.join(timeout=5)
                runtime_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
