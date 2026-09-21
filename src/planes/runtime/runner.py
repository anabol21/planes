"""Run one solver process and map its result onto a ComputeResponse.

The CLI is the only caller. Timeout sends SIGTERM, then SIGKILL.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import signal
import subprocess
import sys
import time
from typing import Any

from planes.runtime.logs import record
from planes.runtime.types import (
    OUTCOMES,
    ComputeRequest,
    ComputeResponse,
    dump_response,
    make_response,
    parse_request,
    request_to_dict,
    safe_job_id,
)

TERM_GRACE_SECONDS = 0.25
_SECRET_ENV = ("COMPUTE_TOKEN", "COMPUTE_HOST", "COMPUTE_TIMEOUT_SECONDS")


def solver_command() -> list[str]:
    raw = os.environ.get("PLANES_SOLVER_ARGV", "").strip()
    if not raw:
        return [sys.executable, "-m", "planes.runtime.placeholder"]
    return shlex.split(raw)


def execute(raw: bytes, timeout_seconds: float) -> ComputeResponse:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        return _error("unknown", 0, "", ["timeout must be a non-negative number of seconds"])
    job_id = "unknown"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("unknown", 0, "", ["request is not JSON"])
    if isinstance(data, dict):
        job_id = safe_job_id(data.get("job_id"))
    try:
        request = parse_request(data)
    except ValueError as exc:
        return _error(job_id, 0, "", [str(exc)])
    return run_solver(request, timeout_seconds)


def run_solver(request: ComputeRequest, timeout_seconds: float) -> ComputeResponse:
    started = time.monotonic()
    proc = subprocess.Popen(
        solver_command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_solver_env(),
        start_new_session=True,
    )
    payload = json.dumps(request_to_dict(request)).encode("utf-8")
    timed_out = False
    try:
        stdout, stderr = proc.communicate(payload, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        stdout, stderr = _stop_process(proc)
    elapsed = time.monotonic() - started
    stderr_text = stderr.decode("utf-8", errors="replace")
    if timed_out:
        log_ref = record(
            request.job_id,
            f"job_id={request.job_id} outcome=timed_out runtime_seconds={elapsed:.6f}",
            stderr_text,
        )
        return make_response(
            job_id=request.job_id,
            outcome="timed_out",
            method="runtime-wrapper",
            objective=request.optimization.objective,
            runtime_seconds=elapsed,
            seed=request.seed,
            limitations=["Solver exceeded the wrapper timeout and was terminated."],
            log_ref=log_ref,
        )
    returncode = proc.returncode if proc.returncode is not None else 1
    if returncode != 0:
        log_ref = record(
            request.job_id,
            f"job_id={request.job_id} outcome=error exit={returncode} runtime_seconds={elapsed:.6f}",
            stderr_text,
        )
        return make_response(
            job_id=request.job_id,
            outcome="error",
            method="runtime-wrapper",
            objective=request.optimization.objective,
            runtime_seconds=elapsed,
            seed=request.seed,
            limitations=[f"Solver exited with status {returncode}."],
            log_ref=log_ref,
        )
    accepted = _accept_solver_stdout(stdout, request)
    if accepted is None:
        log_ref = record(
            request.job_id,
            f"job_id={request.job_id} outcome=error runtime_seconds={elapsed:.6f}",
            stderr_text,
        )
        return make_response(
            job_id=request.job_id,
            outcome="error",
            method="runtime-wrapper",
            objective=request.optimization.objective,
            runtime_seconds=elapsed,
            seed=request.seed,
            limitations=["Solver stdout was not a feasible or infeasible ComputeResponse."],
            log_ref=log_ref,
        )
    outcome, method, mission, limitations = accepted
    log_ref = record(
        request.job_id,
        f"job_id={request.job_id} outcome={outcome} runtime_seconds={elapsed:.6f}",
        stderr_text,
    )
    return make_response(
        job_id=request.job_id,
        outcome=outcome,
        method=method,
        objective=request.optimization.objective,
        runtime_seconds=elapsed,
        seed=request.seed,
        limitations=limitations,
        log_ref=log_ref,
        mission_plan=mission,
    )


def _stop_process(proc: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    _signal_group(proc, signal.SIGTERM)
    try:
        return proc.communicate(timeout=TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_group(proc, signal.SIGKILL)
        return proc.communicate()


def _signal_group(proc: subprocess.Popen[bytes], sig: int) -> None:
    if proc.poll() is not None and sig == signal.SIGTERM:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        if sig == signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()


def _solver_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in _SECRET_ENV:
        env.pop(name, None)
    return env


def _accept_solver_stdout(
    stdout: bytes, request: ComputeRequest
) -> tuple[str, str, dict[str, Any] | None, list[str]] | None:
    try:
        data = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("contract_version") != "v0" or data.get("job_id") != request.job_id:
        return None
    outcome = data.get("outcome")
    if outcome not in {"feasible", "infeasible"} or outcome not in OUTCOMES:
        return None
    report = data.get("solver_report")
    if not isinstance(report, dict):
        return None
    method = report.get("method")
    limitations = report.get("limitations")
    if not isinstance(method, str) or not method:
        return None
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        return None
    mission = data.get("mission_plan") if "mission_plan" in data else None
    if mission is not None and not isinstance(mission, dict):
        return None
    return outcome, method, mission, list(limitations)


def _error(job_id: str, seed: int, objective: str, limitations: list[str]) -> ComputeResponse:
    log_ref = record(job_id, f"job_id={job_id} outcome=error")
    return make_response(
        job_id=job_id,
        outcome="error",
        method="runtime-wrapper",
        objective=objective,
        runtime_seconds=0.0,
        seed=seed,
        limitations=limitations,
        log_ref=log_ref,
    )


def dumps(response: ComputeResponse) -> str:
    return dump_response(response)
