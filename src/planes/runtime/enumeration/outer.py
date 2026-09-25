"""Filter a scenario envelope and build one core ``InputData`` per candidate."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_PADS = 4
MAX_TYPES = 4
MAX_CALLS = 16

_SHARED = (
    "area",
    "criterion",
    "wind",
    "gsd_cm_per_px",
    "survey",
    "power_coeffs",
)
_FLIGHT = (
    "model",
    "mass_kg",
    "max_flight_time_s",
    "battery_wh",
    "v_air_ms",
    "v_vertical_ms",
    "max_wind_ms",
)
_OPTICS = (
    "sensor_width_mm",
    "sensor_height_mm",
    "focal_length_mm",
    "image_width_px",
    "image_height_px",
)
_OK = frozenset({"optimal", "feasible", "heuristic"})
_GIBRID_ROOT = (
    Path(__file__).resolve().parents[2] / "model" / "basic_model" / "gibrid-optimizer"
)

CoreFn = Callable[..., dict[str, Any]]
_input_api: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class Candidate:
    pad_id: str
    type_id: str
    data: Any


@dataclass(frozen=True)
class Attempt:
    pad_id: str
    type_id: str
    data: Any
    result: dict[str, Any]


@dataclass(frozen=True)
class EnumerationResult:
    attempts: tuple[Attempt, ...]
    stopped_for_deadline: bool


@dataclass(frozen=True)
class Winner:
    pad_id: str
    type_id: str
    result: dict[str, Any]
    objective_value: float


def is_outer_scenario(scenario: dict[str, Any]) -> bool:
    return isinstance(scenario, dict) and "pads" in scenario and "uav_types" in scenario


def candidates(scenario: dict[str, Any], *, time_limit_s: int | float = 60) -> list[Candidate]:
    """Admit (pad, type) pairs and build one ``InputData`` for each.

    Order is the envelope order: pads as listed, then the types listed on
    that pad. A pair is kept only when the type is on the pad and its camera
    name and one of its spectra equal the zone requirement.
    """
    planned = _planned(scenario)
    if len(planned) > MAX_CALLS:
        raise ValueError("at most 16 calls")
    limit = _positive_int(time_limit_s, "time_limit_s")
    input_data_cls, validation_error = _input_api_types()
    built: list[Candidate] = []
    for pad_id, type_id, payload in planned:
        payload["solver"] = {"time_limit_s": limit}
        try:
            data = input_data_cls(**payload)
        except validation_error as exc:
            raise ValueError(_invalid_fields(exc)) from exc
        built.append(Candidate(pad_id=pad_id, type_id=type_id, data=data))
    return built


def run_candidates(
    scenario: dict[str, Any],
    *,
    seed: int,
    time_limit_s: int | float,
    core: CoreFn | None = None,
    deadline: float | None = None,
) -> EnumerationResult:
    """Call ``core`` once per admitted candidate. The default core is ``run``."""
    admitted = candidates(scenario, time_limit_s=time_limit_s)
    call = core if core is not None else _default_core
    attempts: list[Attempt] = []
    stopped = False
    for item in admitted:
        limit = _positive_int(time_limit_s, "time_limit_s")
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining < 1:
                stopped = True
                break
            limit = min(limit, int(remaining))
        solver = item.data.solver.model_copy(update={"time_limit_s": limit})
        data = item.data.model_copy(update={"solver": solver})
        result = call(data, seed=seed)
        if not isinstance(result, dict):
            raise ValueError("missing fields: solver result")
        attempts.append(
            Attempt(pad_id=item.pad_id, type_id=item.type_id, data=data, result=result)
        )
    return EnumerationResult(attempts=tuple(attempts), stopped_for_deadline=stopped)


def select_winner(attempts: tuple[Attempt, ...] | list[Attempt], criterion: str) -> Winner | None:
    """Pick the successful call with the smaller mission time. Ties keep the earlier call."""
    if criterion not in ("min_time", "min_flight_hours"):
        raise ValueError("missing fields: criterion")
    field = "mission_time_s" if criterion == "min_time" else "total_flight_time_s"
    best: Attempt | None = None
    best_value: float | None = None
    for attempt in attempts:
        if attempt.result.get("status") not in _OK:
            continue
        mission = attempt.result.get("mission")
        if not isinstance(mission, dict) or field not in mission:
            raise ValueError(f"missing fields: mission.{field}")
        value = float(mission[field])
        if best is None or best_value is None or value < best_value:
            best = attempt
            best_value = value
    if best is None or best_value is None:
        return None
    return Winner(
        pad_id=best.pad_id,
        type_id=best.type_id,
        result=best.result,
        objective_value=best_value,
    )


def _planned(scenario: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    if not isinstance(scenario, dict):
        raise ValueError("missing fields: scenario")
    missing = [name for name in ("required_camera", "required_spectrum", *_SHARED, "uav_types", "pads") if name not in scenario]
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    required_camera = _text(scenario["required_camera"], "required_camera")
    required_spectrum = _text(scenario["required_spectrum"], "required_spectrum")
    if scenario["criterion"] not in ("min_time", "min_flight_hours"):
        raise ValueError("missing fields: criterion")
    types = _types(scenario["uav_types"])
    pads = _pads(scenario["pads"], types)
    shared = {name: scenario[name] for name in _SHARED}
    planned: list[tuple[str, str, dict[str, Any]]] = []
    for pad in pads:
        for stock in pad["types"]:
            vehicle = types[stock["id"]]
            if not _compatible(vehicle, required_camera, required_spectrum):
                continue
            payload = {
                **shared,
                "takeoff": {"lat": pad["lat"], "lon": pad["lon"]},
                "uav": {**vehicle["flight"], "count": stock["count"]},
                "camera": dict(vehicle["optics"]),
            }
            planned.append((pad["id"], vehicle["id"], payload))
    return planned


def _types(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("missing fields: uav_types")
    if len(raw) > MAX_TYPES:
        raise ValueError("at most 4 uav types")
    catalog: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: uav_types[{index}]")
        type_id = _text(item.get("id"), f"uav_types[{index}].id")
        if type_id in catalog:
            raise ValueError(f"duplicate uav type: {type_id}")
        camera = item.get("camera")
        if not isinstance(camera, dict):
            raise ValueError(f"missing fields: uav_types[{index}].camera")
        name = _text(camera.get("name"), f"uav_types[{index}].camera.name")
        missing_optics = [key for key in _OPTICS if key not in camera]
        if missing_optics:
            raise ValueError("missing fields: " + ", ".join(f"uav_types[{index}].camera.{key}" for key in missing_optics))
        spectra = item.get("spectra")
        if not isinstance(spectra, list) or not spectra or not all(isinstance(part, str) for part in spectra):
            raise ValueError(f"missing fields: uav_types[{index}].spectra")
        missing_flight = [key for key in _FLIGHT if key not in item]
        if missing_flight:
            raise ValueError("missing fields: " + ", ".join(f"uav_types[{index}].{key}" for key in missing_flight))
        catalog[type_id] = {
            "id": type_id,
            "camera_name": name,
            "spectra": list(spectra),
            "optics": {key: camera[key] for key in _OPTICS},
            "flight": {key: item[key] for key in _FLIGHT},
        }
    return catalog


def _pads(raw: Any, types: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("missing fields: pads")
    if len(raw) > MAX_PADS:
        raise ValueError("at most 4 pads")
    pads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: pads[{index}]")
        pad_id = _text(item.get("id"), f"pads[{index}].id")
        if pad_id in seen:
            raise ValueError(f"duplicate pad: {pad_id}")
        seen.add(pad_id)
        lat = _coord(item.get("lat"), f"pads[{index}].lat")
        lon = _coord(item.get("lon"), f"pads[{index}].lon")
        listed = item.get("types")
        if not isinstance(listed, list):
            raise ValueError(f"missing fields: pads[{index}].types")
        stock: list[dict[str, Any]] = []
        for type_index, entry in enumerate(listed):
            if not isinstance(entry, dict):
                raise ValueError(f"missing fields: pads[{index}].types[{type_index}]")
            type_id = _text(entry.get("id"), f"pads[{index}].types[{type_index}].id")
            if type_id not in types:
                raise ValueError(f"unknown uav type on pad {pad_id}: {type_id}")
            count = entry.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(f"missing fields: pads[{index}].types[{type_index}].count")
            stock.append({"id": type_id, "count": count})
        pads.append({"id": pad_id, "lat": lat, "lon": lon, "types": stock})
    return pads


def _compatible(vehicle: dict[str, Any], required_camera: str, required_spectrum: str) -> bool:
    return vehicle["camera_name"] == required_camera and required_spectrum in vehicle["spectra"]


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing fields: {label}")
    return value


def _coord(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    return float(value)


def _positive_int(value: int | float, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    limit = int(value)
    if limit < 1 or float(value) != limit:
        raise ValueError(f"missing fields: {label}")
    return limit


def _default_core(data: Any, seed: int = 42) -> dict[str, Any]:
    return _run_optimizer()(data, seed=seed)


def _run_optimizer() -> CoreFn:
    root = str(_GIBRID_ROOT)
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        from optimizer.main import run as run_optimizer
    except ImportError as exc:
        raise ValueError(f"optimizer import failed: {exc}") from exc
    finally:
        if inserted and root in sys.path:
            sys.path.remove(root)
    return run_optimizer


def _input_api_types() -> tuple[Any, Any]:
    global _input_api
    if _input_api is not None:
        return _input_api
    root = str(_GIBRID_ROOT)
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        from optimizer.models import InputData
        from pydantic import ValidationError
    except ImportError as exc:
        raise ValueError(f"optimizer import failed: {exc}") from exc
    finally:
        if inserted and root in sys.path:
            sys.path.remove(root)
    _input_api = (InputData, ValidationError)
    return _input_api


def _invalid_fields(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    seen: list[str] = []
    if callable(errors):
        for err in errors():
            loc = ".".join(str(part) for part in err.get("loc", ()))
            if loc and loc not in seen:
                seen.append(loc)
    if not seen:
        seen.append("scenario")
    return "missing fields: " + ", ".join(seen)
