"""Для агента Руслана.

Caller-side port to the VPS compute listener.

``solve`` always POSTs a ComputeRequest to ``http://$COMPUTE_HOST:8080/v0/solve``.
Host, token, and timeout come from the environment. A missing value is an
error response. This module does not spawn the solver.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from planes.runtime.types import (
    ComputeRequest,
    ComputeResponse,
    make_response,
    parse_response,
    request_to_dict,
)

_REQUIRED = ("COMPUTE_HOST", "COMPUTE_TOKEN", "COMPUTE_TIMEOUT_SECONDS")


class RuntimeEngineAdapter:
    """HTTP client for ``OptimizationEngine.solve``."""

    def solve(self, request: ComputeRequest) -> ComputeResponse:
        if not isinstance(request, ComputeRequest):
            raise TypeError("solve expects a ComputeRequest")
        missing = [name for name in _REQUIRED if not os.environ.get(name, "").strip()]
        if missing:
            listed = ", ".join(missing)
            return _adapter_error(request, f"Missing compute configuration: {listed}.")
        host = os.environ["COMPUTE_HOST"].strip()
        if "/" in host or "\\" in host or " " in host or ":" in host:
            return _adapter_error(request, "COMPUTE_HOST must be a host name without a port.")
        try:
            timeout = float(os.environ["COMPUTE_TIMEOUT_SECONDS"].strip())
        except ValueError:
            return _adapter_error(
                request, "COMPUTE_TIMEOUT_SECONDS must be a positive number of seconds."
            )
        if timeout <= 0:
            return _adapter_error(
                request, "COMPUTE_TIMEOUT_SECONDS must be a positive number of seconds."
            )
        token = os.environ["COMPUTE_TOKEN"]
        payload = json.dumps(request_to_dict(request), ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            url=f"http://{host}:8080/v0/solve",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(http_request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            return _adapter_error(request, f"Compute listener returned HTTP {exc.code}.")
        except (TimeoutError, socket.timeout):
            return _adapter_timeout(request)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return _adapter_timeout(request)
            return _adapter_error(request, "Compute listener is unreachable.")
        except json.JSONDecodeError:
            return _adapter_error(request, "Compute listener returned invalid JSON.")
        try:
            return parse_response(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return _adapter_error(request, "Compute listener returned invalid JSON.")


def _adapter_error(request: ComputeRequest, limitation: str) -> ComputeResponse:
    return make_response(
        job_id=request.job_id,
        outcome="error",
        method="runtime-adapter",
        objective=request.optimization.objective,
        runtime_seconds=0.0,
        seed=request.seed,
        limitations=[limitation, "No solver result was produced."],
    )


def _adapter_timeout(request: ComputeRequest) -> ComputeResponse:
    return make_response(
        job_id=request.job_id,
        outcome="timed_out",
        method="runtime-adapter",
        objective=request.optimization.objective,
        runtime_seconds=0.0,
        seed=request.seed,
        limitations=["Client wait for the compute listener expired."],
    )
