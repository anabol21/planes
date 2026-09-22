"""SQLite persistence for backend-owned job lifecycle state."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .models import ComputeResponse


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    contract_version: str
    state: str
    scenario: dict[str, Any]
    optimization: dict[str, Any]
    seed: int
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class SQLiteJobStore:
    """Durable prototype store; each operation uses its own connection."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    contract_version TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('queued', 'running', 'completed', 'failed', 'timed_out')
                    ),
                    scenario_json TEXT NOT NULL,
                    optimization_json TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_queued_idx ON jobs(state, created_at, job_id)"
            )

    def create_job(
        self,
        *,
        job_id: str,
        contract_version: str,
        scenario_json: str,
        optimization_json: str,
        seed: int,
    ) -> JobRecord:
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, contract_version, state, scenario_json,
                    optimization_json, seed, created_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?)
                """,
                (job_id, contract_version, scenario_json, optimization_json, seed, created_at),
            )
        record = self.get_job(job_id)
        if record is None:  # pragma: no cover - guards storage corruption
            raise RuntimeError("created job could not be reloaded")
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._to_record(row) if row is not None else None

    def claim_next_queued_job(self) -> JobRecord | None:
        """Atomically move one queued job to running and return it.

        BEGIN IMMEDIATE serializes competing writers. The conditional update is a
        second guard that prevents a stale selection from becoming a double claim.
        """
        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE state = 'queued'
                ORDER BY created_at, job_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            job_id = row["job_id"]
            updated = connection.execute(
                """
                UPDATE jobs
                SET state = 'running', started_at = ?
                WHERE job_id = ? AND state = 'queued'
                """,
                (_now(), job_id),
            )
            if updated.rowcount != 1:
                connection.execute("ROLLBACK")
                return None
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.execute("COMMIT")
            return self._to_record(claimed)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def finish_with_response(self, job_id: str, response: ComputeResponse) -> None:
        if response.job_id != job_id:
            raise ValueError("engine response job_id does not match claimed job")
        finished_at = _now()
        payload = json.dumps(response.to_dict(), sort_keys=True, separators=(",", ":"))
        if response.outcome in {"feasible", "infeasible"}:
            state, result_json, error_json = "completed", payload, None
        elif response.outcome == "timed_out":
            state, result_json, error_json = "timed_out", payload, None
        else:
            state, result_json, error_json = "failed", None, payload
        self._finish(job_id, state, result_json, error_json, finished_at)

    def mark_failed(self, job_id: str, error: Mapping[str, Any]) -> None:
        error_json = json.dumps(dict(error), sort_keys=True, separators=(",", ":"))
        self._finish(job_id, "failed", None, error_json, _now())

    def _finish(
        self,
        job_id: str,
        state: str,
        result_json: str | None,
        error_json: str | None,
        finished_at: str,
    ) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE jobs
                SET state = ?, result_json = ?, error_json = ?, finished_at = ?
                WHERE job_id = ? AND state = 'running'
                """,
                (state, result_json, error_json, finished_at, job_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError(f"job {job_id} is not in running state")

    @staticmethod
    def _to_record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            contract_version=row["contract_version"],
            state=row["state"],
            scenario=json.loads(row["scenario_json"]),
            optimization=json.loads(row["optimization_json"]),
            seed=row["seed"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
