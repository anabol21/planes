"""Shared helpers for runtime tests.

An HTTP server started on 127.0.0.1 is a test double for the VPS listener.
It is not a second way to run the engine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "compute_request_v0.json"
TOKEN = "test-token-do-not-print"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from planes.runtime.http_server import ComputeHTTPServer, ComputeHandler  # noqa: E402
from planes.runtime.types import ComputeRequest, parse_request  # noqa: E402


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def request_from_fixture(**optimization: object) -> ComputeRequest:
    data = load_fixture()
    data["optimization"].update(optimization)
    return parse_request(data)


@contextmanager
def env_vars(**updates: str | None) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_cli(payload: dict[str, Any] | None, timeout: str, *, request_path: str | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["COMPUTE_TOKEN"] = TOKEN
    command = [
        sys.executable,
        "-m",
        "planes.runtime.cli",
        "solve",
        "--request",
        request_path or "-",
        "--timeout-seconds",
        timeout,
    ]
    proc = subprocess.run(
        command,
        input=None if request_path else json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=8,
        check=False,
    )
    stdout = proc.stdout.decode("utf-8")
    stderr = proc.stderr.decode("utf-8")
    if TOKEN in stdout or TOKEN in stderr:
        raise AssertionError("compute token leaked into CLI output")
    if proc.returncode != 0:
        raise AssertionError(f"CLI exited {proc.returncode}: {stderr}")
    body = json.loads(stdout)
    for artifact in body.get("artifacts", []):
        if artifact.get("kind") == "log":
            text = Path(artifact["ref"]).read_text(encoding="utf-8")
            if TOKEN in text:
                raise AssertionError("compute token leaked into the job log")
    return body


@contextmanager
def vps_listener(token: str = TOKEN) -> Iterator[Path]:
    """Bind the product listener on 127.0.0.1:8080."""
    lock_dir = Path(tempfile.mkdtemp(prefix="planes-lock-"))
    lock_path = lock_dir / "job.lock"
    with env_vars(COMPUTE_TOKEN=token, PLANES_LOCK_PATH=str(lock_path), PYTHONPATH=str(SRC)):
        server = ComputeHTTPServer(("127.0.0.1", 8080), ComputeHandler)
        thread = threading.Thread(target=server.serve_forever, name="planes-compute-test", daemon=True)
        thread.start()
        _wait_for_health()
        try:
            yield lock_path
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def _wait_for_health() -> None:
    deadline = time.monotonic() + 3
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=0.2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def post_json(payload: dict[str, Any], token: str | None, timeout: float = 8) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "http://127.0.0.1:8080/v0/solve",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
