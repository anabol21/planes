"""Thin standard-library WSGI adapter exposing the RUS-001 HTTP endpoints."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterable
from typing import Any
from wsgiref.simple_server import make_server

from .service import (
    BackendService,
    JobNotFoundError,
    ResultNotReadyError,
    ValidationError,
)
from .store import SQLiteJobStore


StartResponse = Callable[[str, list[tuple[str, str]]], Any]
_JOB_PATH = re.compile(r"^/jobs/([^/]+)$")
_RESULT_PATH = re.compile(r"^/jobs/([^/]+)/result$")


class BackendAPI:
    def __init__(self, service: BackendService) -> None:
        self.service = service

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "")
        try:
            if method == "POST" and path == "/jobs":
                payload = self._read_body(environ)
                status = self.service.submit_job(
                    scenario=payload.get("scenario"),
                    optimization=payload.get("optimization"),
                    seed=payload.get("seed"),
                    contract_version=payload.get("contract_version", "v0"),
                    job_id=payload.get("job_id"),
                )
                return self._respond(start_response, "202 Accepted", status, [("Location", f"/jobs/{status['job_id']}")])

            result_match = _RESULT_PATH.match(path)
            if method == "GET" and result_match:
                return self._respond(start_response, "200 OK", self.service.get_result(result_match.group(1)))

            job_match = _JOB_PATH.match(path)
            if method == "GET" and job_match:
                return self._respond(start_response, "200 OK", self.service.get_job(job_match.group(1)))

            if path == "/jobs" or job_match or result_match:
                return self._respond(start_response, "405 Method Not Allowed", {"error": "method_not_allowed"})
            return self._respond(start_response, "404 Not Found", {"error": "not_found"})
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return self._respond(start_response, "400 Bad Request", {"error": "invalid_request", "message": str(error)})
        except JobNotFoundError:
            return self._respond(start_response, "404 Not Found", {"error": "job_not_found"})
        except ResultNotReadyError as error:
            return self._respond(start_response, "409 Conflict", {"error": "result_not_ready", "state": str(error)})

    @staticmethod
    def _read_body(environ: dict[str, Any]) -> dict[str, Any]:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError as error:
            raise ValidationError("invalid Content-Length") from error
        if length <= 0 or length > 1_000_000:
            raise ValidationError("request body must be between 1 and 1000000 bytes")
        body = environ["wsgi.input"].read(length)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")
        return payload

    @staticmethod
    def _respond(
        start_response: StartResponse,
        status: str,
        payload: dict[str, Any],
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> list[bytes]:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        headers.extend(extra_headers or [])
        start_response(status, headers)
        return [body]


def create_app(database: str) -> BackendAPI:
    return BackendAPI(BackendService(SQLiteJobStore(database)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the RUS-001 prototype API")
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with make_server(args.host, args.port, create_app(args.database)) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a process
    raise SystemExit(main())
