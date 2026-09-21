"""Runtime, не точка интеграции.

Stdlib HTTP listener for the VPS compute contour.

GET /health is unauthenticated liveness. POST /v0/solve checks
``COMPUTE_TOKEN`` and spawns ``python -m planes.runtime.cli`` for that job.
The listener does not solve the mission itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from planes.runtime.lock import JobLock, default_lock_path
from planes.runtime.logs import redact
from planes.runtime.types import dump_response, make_response, parse_response, safe_job_id

MAX_BODY_BYTES = 1_048_576
_CLI_BUFFER_SECONDS = 2.0


class ComputeHandler(BaseHTTPRequestHandler):
    server_version = "planes-compute/v0"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if urlsplit(self.path).path != "/health":
            self._send_json(404, {"contract_version": "v0", "error": "not_found"})
            return
        self._send_json(200, {"status": "live", "contract_version": "v0"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        if urlsplit(self.path).path != "/v0/solve":
            self._send_json(404, {"contract_version": "v0", "error": "not_found"})
            return
        if not _authorized(self.headers.get("Authorization"), self.server.compute_token):
            self._send_json(401, {"contract_version": "v0", "error": "unauthorized"})
            return
        body, error = self._read_body()
        if error is not None:
            self._send_json(400, {"contract_version": "v0", "error": error})
            return
        lock = JobLock(default_lock_path())
        if not lock.try_acquire():
            self._send_json(503, {"contract_version": "v0", "error": "busy"})
            return
        try:
            payload = _run_cli(body)
        finally:
            lock.release()
        self._send_bytes(200, payload)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("planes-compute " + (fmt % args) + "\n")

    def _read_body(self) -> tuple[bytes, str | None]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            return b"", "invalid_content_length"
        if length < 0:
            return b"", "invalid_content_length"
        if length > MAX_BODY_BYTES:
            return b"", "body_too_large"
        if length == 0:
            return b"", None
        return self.rfile.read(length), None

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        self._send_bytes(status, json.dumps(payload).encode("utf-8"))

    def _send_bytes(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ComputeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], request_handler_class: type[ComputeHandler]) -> None:
        super().__init__(server_address, request_handler_class)
        # Fixed for the process lifetime. Callers keep their own COMPUTE_TOKEN.
        self.compute_token = os.environ.get("COMPUTE_TOKEN", "")


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    server = ComputeHTTPServer((host, port), ComputeHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planes.runtime.http_server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


def _authorized(header: str | None, expected: str) -> bool:
    import hmac

    if not expected or not header or not header.startswith("Bearer "):
        return False
    presented = header[len("Bearer ") :]
    if len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def _run_cli(body: bytes) -> bytes:
    timeout_seconds = _timeout_from_body(body)
    env = os.environ.copy()
    env.pop("COMPUTE_TOKEN", None)
    command = [
        sys.executable,
        "-m",
        "planes.runtime.cli",
        "solve",
        "--request",
        "-",
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    try:
        completed = subprocess.run(
            command,
            input=body,
            capture_output=True,
            timeout=timeout_seconds + _CLI_BUFFER_SECONDS,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _forward_stderr(exc.stderr if isinstance(exc.stderr, bytes) else None)
        return _synthesized("timed_out", body, ["CLI did not return before the listener deadline."])
    _forward_stderr(completed.stderr)
    try:
        parsed = json.loads(completed.stdout.decode("utf-8"))
        parse_response(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return _synthesized("error", body, ["CLI stdout was not a ComputeResponse."])
    if completed.stdout.endswith(b"\n"):
        return completed.stdout
    return completed.stdout + b"\n"


def _forward_stderr(payload: bytes | None) -> None:
    if not payload:
        return
    text = redact(payload.decode("utf-8", errors="replace"))
    sys.stderr.write(text)
    if not text.endswith("\n"):
        sys.stderr.write("\n")


def _timeout_from_body(body: bytes) -> float:
    try:
        data = json.loads(body.decode("utf-8"))
        value = data["optimization"]["time_limit_seconds"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return 1.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 1.0
    return float(value)


def _synthesized(outcome: str, body: bytes, limitations: list[str]) -> bytes:
    job_id = "unknown"
    try:
        data = json.loads(body.decode("utf-8"))
        if isinstance(data, dict):
            job_id = safe_job_id(data.get("job_id"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        job_id = "unknown"
    response = make_response(
        job_id=job_id,
        outcome=outcome,
        method="runtime-listener",
        objective="",
        runtime_seconds=0.0,
        seed=0,
        limitations=limitations,
    )
    return dump_response(response).encode("utf-8")


if __name__ == "__main__":
    sys.exit(main())
