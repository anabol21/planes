"""Backend use cases independent of HTTP and optimizer implementation details."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from .models import CONTRACT_VERSION
from .store import JobRecord, SQLiteJobStore


class ValidationError(ValueError):
    pass


class JobNotFoundError(LookupError):
    pass


class ResultNotReadyError(RuntimeError):
    pass


class BackendService:
    def __init__(self, store: SQLiteJobStore) -> None:
        self.store = store

    def submit_job(
        self,
        *,
        scenario: Mapping[str, Any],
        optimization: Mapping[str, Any],
        seed: int,
        contract_version: str = CONTRACT_VERSION,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if contract_version != CONTRACT_VERSION:
            raise ValidationError(f"contract_version must be {CONTRACT_VERSION!r}")
        if not isinstance(scenario, Mapping) or not scenario:
            raise ValidationError("scenario must be a non-empty JSON object")
        if not isinstance(optimization, Mapping):
            raise ValidationError("optimization must be a JSON object")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValidationError("seed must be an integer")
        if job_id is None:
            job_id = str(uuid.uuid4())
        elif not isinstance(job_id, str) or not job_id.strip():
            raise ValidationError("job_id must be a non-empty string")

        scenario_json = self._snapshot_json(scenario, "scenario")
        optimization_json = self._snapshot_json(optimization, "optimization")
        record = self.store.create_job(
            job_id=job_id,
            contract_version=contract_version,
            scenario_json=scenario_json,
            optimization_json=optimization_json,
            seed=seed,
        )
        return self._status_view(record)

    def get_job(self, job_id: str) -> dict[str, Any]:
        record = self.store.get_job(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return self._status_view(record)

    def get_result(self, job_id: str) -> dict[str, Any]:
        record = self.store.get_job(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        if record.state in {"queued", "running"}:
            raise ResultNotReadyError(record.state)
        if record.state == "failed":
            return {
                "contract_version": record.contract_version,
                "job_id": record.job_id,
                "state": record.state,
                "error": record.error,
            }
        if record.result is None:
            raise RuntimeError(f"terminal job {job_id} has no result")
        return {"state": record.state, **record.result}

    @staticmethod
    def _snapshot_json(value: Mapping[str, Any], name: str) -> str:
        try:
            return json.dumps(
                dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as error:
            raise ValidationError(f"{name} must contain only finite JSON data") from error

    @staticmethod
    def _status_view(record: JobRecord) -> dict[str, Any]:
        return {
            "contract_version": record.contract_version,
            "job_id": record.job_id,
            "state": record.state,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        }
