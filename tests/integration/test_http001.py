"""HTTP-001: ingress boundaries, startup policy, and large KML transport.

No compute execution, terrain HTTP, or optimizer is used.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planes.backend.api import BackendAPI
from planes.backend.service import BackendService, ValidationError
from planes.backend.store import SQLiteJobStore
from planes.integration.http_body import DEFAULT_MAX_REQUEST_BODY_BYTES, request_body_limit
from planes.runtime.http_server import ComputeHandler, ComputeHTTPServer
from planes.runtime.pipeline import bind, compile, ingest

ENV = "PLANES_MAX_REQUEST_BODY_BYTES"


class ReadSpy(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


def large_request(size: int = 1_800_000) -> bytes:
    """Keep a valid polygon; grow KML description instead of JSON whitespace."""
    kml = (
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        '<description>{padding}</description><Placemark><Polygon>'
        '<outerBoundaryIs><LinearRing><coordinates>'
        '37.600,55.750,0 37.608,55.750,0 37.608,55.754,0 '
        '37.600,55.754,0 37.600,55.750,0'
        '</coordinates></LinearRing></outerBoundaryIs></Polygon>'
        '</Placemark></Document></kml>'
    )
    request = {
        "contract_version": "v0", "job_id": "http001-large", "seed": 7,
        "optimization": {"objective": "min_time", "time_limit_seconds": 60},
        "scenario": {
            "scenario_id": "http001-training", "crs": "EPSG:4326",
            "criterion": "min_time", "gsd_cm_per_px": 2,
            "required_spectrum": "RGB", "survey_kml": kml.format(padding=""),
            "constraints_kml": "",
            "aerodromes": [{"id": "a1", "lat": 55.748, "lon": 37.604}],
            "boards": [{"id": "b1", "model_id": "geoscan-gemini",
                        "camera_id": "geoscan-pf1b", "aerodrome_id": "a1", "count": 1}],
            "survey": {"forward_overlap": 0.6, "side_overlap": 0.5,
                       "strip_direction_deg": 0},
            "wind": {"speed_ms": 1, "direction_deg": 90},
        },
    }
    encode = lambda: json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
    request["scenario"]["survey_kml"] = kml.format(padding="x" * (size - len(encode())))
    body = encode()
    assert len(body) == size
    return body


class Http001Test(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        os.environ.pop(ENV, None)
        self.addCleanup(self.env.stop)
        self.api = BackendAPI(Mock())
        self.server = ComputeHTTPServer(("127.0.0.1", 0), ComputeHandler)
        self.addCleanup(self.server.server_close)

    def runtime_reader(self, body: bytes, length: str | None = None):
        stream = ReadSpy(body)
        handler = SimpleNamespace(
            server=self.server, headers={"Content-Length": str(len(body)) if length is None else length},
            rfile=stream,
        )
        return ComputeHandler._read_body(handler), stream

    def backend_reader(self, body: bytes, length: str | None = None):
        stream = ReadSpy(body)
        env = {"CONTENT_LENGTH": str(len(body)) if length is None else length, "wsgi.input": stream}
        return env, stream

    def test_default_and_consistency(self):
        self.assertEqual(request_body_limit(), 10_485_760)
        self.assertEqual(self.api.max_request_body_bytes, self.server.max_request_body_bytes)

    def test_boundaries_at_both_readers(self):
        for size in [1, 1_000_000, 1_000_001, 1_048_576, 1_048_577, 1_800_000, 10_485_760]:
            with self.subTest(size=size):
                body = b"0" if size == 1 else b"{}" + b" " * (size - 2)
                env, stream = self.backend_reader(body)
                if size == 1:
                    with self.assertRaisesRegex(ValidationError, "JSON object"):
                        self.api._read_body(env)
                else:
                    self.assertEqual(self.api._read_body(env), {})
                self.assertEqual(stream.read_sizes, [size])
                (result, error), stream = self.runtime_reader(body)
                self.assertIsNone(error)
                self.assertEqual(result, body)
                self.assertEqual(stream.read_sizes, [size])

    def test_oversized_is_rejected_before_any_read_or_job(self):
        size = DEFAULT_MAX_REQUEST_BODY_BYTES + 1
        env, stream = self.backend_reader(b"", str(size))
        env.update(REQUEST_METHOD="POST", PATH_INFO="/jobs")
        status = []
        response = self.api(env, lambda code, headers: status.append(code))
        self.assertEqual(status, ["400 Bad Request"])
        self.assertIn("10485760", json.loads(b"".join(response))["message"])
        self.assertEqual(stream.read_sizes, [])
        self.api.service.submit_job.assert_not_called()
        (body, error), stream = self.runtime_reader(b"", str(size))
        self.assertEqual(error, "body_too_large")
        self.assertEqual(stream.read_sizes, [])

    def test_runtime_oversized_response_contains_effective_max_and_never_solves(self):
        handler = SimpleNamespace(
            path="/v0/solve", server=SimpleNamespace(compute_token="test-only", max_request_body_bytes=10_485_760),
            headers={"Authorization": "Bearer test-only"},
            _read_body=lambda: (b"", "body_too_large"), _send_json=Mock(),
        )
        with patch("planes.runtime.http_server._run_cli") as solve:
            ComputeHandler.do_POST(handler)
            solve.assert_not_called()
        status, payload = handler._send_json.call_args.args
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "body_too_large")
        self.assertIn("10485760", payload["message"])

    def test_empty_and_missing_lengths_are_bounded(self):
        for length in ["0", ""]:
            env, stream = self.backend_reader(b"oversized ignored data", length)
            with self.assertRaisesRegex(ValidationError, "between 1"):
                self.api._read_body(env)
            self.assertEqual(stream.read_sizes, [])
            (_, error), stream = self.runtime_reader(b"oversized ignored data", length)
            self.assertEqual(error, "empty_body" if length == "0" else "invalid_content_length")
            self.assertEqual(stream.read_sizes, [])
        stream = ReadSpy(b"ignored body")
        handler = SimpleNamespace(server=self.server, headers={}, rfile=stream)
        self.assertEqual(ComputeHandler._read_body(handler)[1], "empty_body")
        self.assertEqual(stream.read_sizes, [])

    def test_invalid_and_truncated_content_lengths(self):
        for length in ["-1", "abc"]:
            env, stream = self.backend_reader(b"", length)
            with self.assertRaises(ValidationError):
                self.api._read_body(env)
            self.assertEqual(stream.read_sizes, [])
            (_, error), stream = self.runtime_reader(b"", length)
            self.assertEqual(error, "invalid_content_length")
            self.assertEqual(stream.read_sizes, [])
        env, stream = self.backend_reader(b"{}", "3")
        with self.assertRaisesRegex(ValidationError, "does not match"):
            self.api._read_body(env)
        (_, error), stream = self.runtime_reader(b"{}", "3")
        self.assertEqual(error, "invalid_body_length")
        self.assertEqual(stream.read_sizes, [3])

    def test_custom_limit_shared_and_frozen_at_startup(self):
        os.environ[ENV] = "2097152"
        api = BackendAPI(Mock())
        with ComputeHTTPServer(("127.0.0.1", 0), ComputeHandler) as server:
            self.assertEqual(api.max_request_body_bytes, server.max_request_body_bytes)
            self.assertEqual(server.max_request_body_bytes, 2_097_152)
            for size in [1_800_000, 2_097_152]:
                body = b"{}" + b" " * (size - 2)
                env, stream = self.backend_reader(body)
                self.assertEqual(api._read_body(env), {})
                handler = SimpleNamespace(server=server, headers={"Content-Length": str(size)}, rfile=ReadSpy(body))
                self.assertEqual(ComputeHandler._read_body(handler), (body, None))
            os.environ[ENV] = "invalid-later"
            env, _ = self.backend_reader(b"", "2097153")
            with self.assertRaisesRegex(ValidationError, "2097152"):
                api._read_body(env)
            handler = SimpleNamespace(server=server, headers={"Content-Length": "2097153"}, rfile=ReadSpy(b""))
            self.assertEqual(ComputeHandler._read_body(handler)[1], "body_too_large")

    def test_invalid_config_fails_both_startups(self):
        for value in ["0", "-1", "abc", "1.5", ""]:
            with self.subTest(value=value), patch.dict(os.environ, {ENV: value}):
                with self.assertRaisesRegex(ValueError, ENV):
                    BackendAPI(Mock())
                with self.assertRaisesRegex(ValueError, ENV):
                    ComputeHTTPServer(("127.0.0.1", 0), ComputeHandler)

    def test_large_training_json_creates_job_and_passes_runtime_ingest(self):
        body = large_request()
        with tempfile.TemporaryDirectory(prefix="http001-") as tmp:
            store = SQLiteJobStore(Path(tmp) / "jobs.sqlite3")
            api = BackendAPI(BackendService(store))
            env, _ = self.backend_reader(body)
            env.update(REQUEST_METHOD="POST", PATH_INFO="/jobs")
            status = []
            response = json.loads(b"".join(api(env, lambda code, headers: status.append(code))))
            self.assertEqual(status, ["202 Accepted"])
            saved = store.get_job(response["job_id"])
            self.assertEqual(saved.state, "queued")
            self.assertEqual(saved.scenario, json.loads(body)["scenario"])
        (received, error), _ = self.runtime_reader(body)
        self.assertIsNone(error)
        problem = compile(bind(ingest(received)))
        self.assertEqual(problem.scenario, json.loads(body)["scenario"])


if __name__ == "__main__":
    unittest.main()
