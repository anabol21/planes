"""Early wind-vs-catalog feasibility check on the API/worker layer.

Reads ``scenario.wind.speed_ms`` (the wrap form field) and
``uav_models[].max_wind_m_s`` from ``fleet_catalog.json``. Does not call
the optimizer or change VPS packing.

Rule when a model has no wind limit
-----------------------------------
A missing, non-finite, or non-positive ``max_wind_m_s`` is **unknown**.
Unknown models do not raise ``fleet_max_wind_mps``. The filter refuses
only when at least one selected board has a known limit and
``wind.speed_ms`` is strictly greater than that fleet maximum. If every
selected model is unknown, the check is skipped (no invented refusal).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import ComputeRequest, ComputeResponse, thaw_json

CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "runtime" / "catalog" / "fleet_catalog.json"
)
LIMITATION_PREFIX = "wind_mps="
METHOD = "api_wind_filter"


@dataclass(frozen=True, slots=True)
class WindRefusal:
    wind_mps: float
    fleet_max_wind_mps: float
    limiting_model_id: str
    unknown_model_ids: tuple[str, ...]

    def limitation(self) -> str:
        return (
            f"wind_mps={self.wind_mps} exceeds fleet_max_wind_mps="
            f"{self.fleet_max_wind_mps} (limiting model_id={self.limiting_model_id})"
        )


def load_fleet_catalog(path: Path | None = None) -> Mapping[str, Any]:
    catalog_path = path or CATALOG_PATH
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fleet catalog must be a JSON object")
    return payload


def marked_positive_number(raw: Any) -> float | None:
    """Read a catalog marked number; unknown/blank values stay unknown."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) and value > 0 else None
    if isinstance(raw, Mapping):
        return marked_positive_number(raw.get("value"))
    return None


def scenario_wind_mps(scenario: Mapping[str, Any]) -> float | None:
    """Prefer the wrap form field ``wind.speed_ms``."""
    wind = scenario.get("wind")
    if not isinstance(wind, Mapping):
        return None
    for key in ("speed_ms", "speed_m_s", "speed_mps"):
        raw = wind.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        value = float(raw)
        if math.isfinite(value) and value >= 0:
            return value
    return None


def evaluate_wind_against_fleet(
    scenario: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
) -> WindRefusal | None:
    """Return a refusal when catalog data is enough to prove the wind is too strong."""
    wind_mps = scenario_wind_mps(scenario)
    if wind_mps is None:
        return None
    boards = scenario.get("boards")
    if not isinstance(boards, list) or not boards:
        return None
    models = _model_index(catalog if catalog is not None else load_fleet_catalog())
    known: list[tuple[str, float]] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for board in boards:
        if not isinstance(board, Mapping):
            continue
        model_id = board.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        record = models.get(model_id)
        limit = marked_positive_number(record.get("max_wind_m_s") if record else None)
        if limit is None:
            unknown.append(model_id)
            continue
        known.append((model_id, limit))
    if not known:
        return None
    limiting_model_id, fleet_max = max(known, key=lambda item: item[1])
    if wind_mps <= fleet_max:
        return None
    return WindRefusal(
        wind_mps=wind_mps,
        fleet_max_wind_mps=fleet_max,
        limiting_model_id=limiting_model_id,
        unknown_model_ids=tuple(unknown),
    )


def refuse_if_wind_exceeds_fleet(
    request: ComputeRequest,
    catalog: Mapping[str, Any] | None = None,
) -> ComputeResponse | None:
    refusal = evaluate_wind_against_fleet(thaw_json(request.scenario), catalog)
    if refusal is None:
        return None
    limitations = [refusal.limitation()]
    if refusal.unknown_model_ids:
        limitations.append(
            "unknown max_wind_m_s for model_id="
            + ",".join(refusal.unknown_model_ids)
        )
    return ComputeResponse(
        job_id=request.job_id,
        outcome="infeasible",
        solver_report={
            "method": METHOD,
            "objective": request.optimization.get("objective") or "",
            "runtime_seconds": 0.0,
            "seed": request.seed,
            "limitations": limitations,
        },
    )


def _model_index(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = catalog.get("uav_models")
    if not isinstance(rows, list):
        return {}
    found: dict[str, Mapping[str, Any]] = {}
    for item in rows:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            found[item["id"]] = item
    return found
