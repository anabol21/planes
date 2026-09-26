"""Build one core ``InputData`` per board card.

A card names a catalog model, a compatible camera, an aerodrome, and a count.
A card is a flight candidate only when ``required_spectrum`` is one of that
camera's catalog spectra. Calls are not merged. This module does not read
zone or terrain KML.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_AERODROMES = 4
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
_PIXELS = ("image_width_px", "image_height_px")
# Catalog fields that fill ``_FLIGHT`` besides the two the brief names.
_OTHER_FLIGHT = (
    ("mass_kg", "mass_kg"),
    ("flight_time_s", "max_flight_time_s"),
    ("climb_m_s", "v_vertical_ms"),
    ("max_wind_m_s", "max_wind_ms"),
)
_OK = frozenset({"optimal", "feasible", "heuristic"})
_NO_RUNNABLE = "no runnable board"
_NO_SPECTRUM = "no camera covers required spectrum"
_CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "fleet_catalog.json"
_GIBRID_ROOT = (
    Path(__file__).resolve().parents[2] / "model" / "basic_model" / "gibrid-optimizer"
)

CoreFn = Callable[..., dict[str, Any]]
_input_api: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class Candidate:
    aerodrome_id: str
    board_id: str
    model_id: str
    camera_id: str
    data: Any


@dataclass(frozen=True)
class Attempt:
    aerodrome_id: str
    board_id: str
    model_id: str
    camera_id: str
    data: Any
    result: dict[str, Any]


@dataclass(frozen=True)
class Skip:
    model_id: str
    camera_id: str
    missing: tuple[str, ...]


@dataclass(frozen=True)
class SpectrumMismatch:
    model_id: str
    camera_id: str
    required_spectrum: str
    camera_spectra: tuple[str, ...]


@dataclass(frozen=True)
class EnumerationResult:
    attempts: tuple[Attempt, ...]
    stopped_for_deadline: bool
    skips: tuple[Skip, ...] = ()
    mismatches: tuple[SpectrumMismatch, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Winner:
    aerodrome_id: str
    board_id: str
    model_id: str
    camera_id: str
    result: dict[str, Any]
    objective_value: float


def is_outer_scenario(scenario: dict[str, Any]) -> bool:
    """An outer envelope has aerodromes and boards, and neither pads nor ``uav_types``."""
    return (
        isinstance(scenario, dict)
        and "aerodromes" in scenario
        and "boards" in scenario
        and "pads" not in scenario
        and "uav_types" not in scenario
    )


def skip_limitation(skip: Skip) -> str:
    return (
        f"skipped model {skip.model_id} camera {skip.camera_id}: "
        f"missing {', '.join(skip.missing)}"
    )


def spectrum_mismatch_limitation(mismatch: SpectrumMismatch) -> str:
    spectra = ", ".join(mismatch.camera_spectra)
    return (
        f"spectrum mismatch model {mismatch.model_id} camera {mismatch.camera_id}: "
        f"required {mismatch.required_spectrum}, camera spectra {spectra}"
    )


def load_catalog() -> dict[str, Any]:
    """Read ``fleet_catalog.json``. Callers do not invent values for empty cells."""
    try:
        raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"fleet catalog unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("missing fields: fleet catalog")
    return raw


def candidates(scenario: dict[str, Any], *, time_limit_s: int | float = 60) -> list[Candidate]:
    """Admit runnable board cards and build one ``InputData`` each.

    Order is the card order. A board is admitted only when
    ``required_spectrum`` is one of that camera's catalog spectra. A
    compatible pair that matches the spectrum but lacks optics or flight
    numbers is skipped. A camera with no compatibility edge to the model is
    rejected.
    """
    admitted, _skips, _mismatches = _prepare(scenario, time_limit_s=time_limit_s)
    return admitted


def run_candidates(
    scenario: dict[str, Any],
    *,
    seed: int,
    time_limit_s: int | float,
    core: CoreFn | None = None,
    deadline: float | None = None,
) -> EnumerationResult:
    """Call ``core`` once per admitted board card. The default core is ``run``.

    Incomplete cards that match the spectrum are recorded and are not calls.
    A spectrum mismatch is recorded and is not a call. No runnable card means
    no core call.
    """
    admitted, skips, mismatches = _prepare(scenario, time_limit_s=time_limit_s)
    recorded = tuple(skips)
    recorded_mismatches = tuple(mismatches)
    if not admitted:
        return EnumerationResult(
            attempts=(),
            stopped_for_deadline=False,
            skips=recorded,
            mismatches=recorded_mismatches,
            reason=_empty_reason(recorded, recorded_mismatches),
        )
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
            Attempt(
                aerodrome_id=item.aerodrome_id,
                board_id=item.board_id,
                model_id=item.model_id,
                camera_id=item.camera_id,
                data=data,
                result=result,
            )
        )
    return EnumerationResult(
        attempts=tuple(attempts),
        stopped_for_deadline=stopped,
        skips=recorded,
        mismatches=recorded_mismatches,
    )


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
        aerodrome_id=best.aerodrome_id,
        board_id=best.board_id,
        model_id=best.model_id,
        camera_id=best.camera_id,
        result=best.result,
        objective_value=best_value,
    )


def _prepare(
    scenario: dict[str, Any],
    *,
    time_limit_s: int | float,
) -> tuple[list[Candidate], list[Skip], list[SpectrumMismatch]]:
    if not isinstance(scenario, dict):
        raise ValueError("missing fields: scenario")
    if "uav_types" in scenario:
        raise ValueError("uav_types is not accepted")
    if "pads" in scenario:
        raise ValueError("pads is not accepted")
    missing = [
        name
        for name in ("required_spectrum", *_SHARED, "aerodromes", "boards")
        if name not in scenario
    ]
    if missing:
        raise ValueError("missing fields: " + ", ".join(missing))
    required_spectrum = _text(scenario["required_spectrum"], "required_spectrum")
    if scenario["criterion"] not in ("min_time", "min_flight_hours"):
        raise ValueError("missing fields: criterion")
    aerodromes = _aerodromes(scenario["aerodromes"])
    boards = _boards(scenario["boards"], aerodromes)
    catalog = load_catalog()
    models = _index(catalog.get("uav_models"), "uav_models")
    cameras = _index(catalog.get("cameras"), "cameras")
    edges = _compatibility(catalog, models, cameras)
    by_aerodrome = {item["id"]: item for item in aerodromes}
    runnable: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    skips: list[Skip] = []
    mismatches: list[SpectrumMismatch] = []
    for board in boards:
        model_id = board["model_id"]
        camera_id = board["camera_id"]
        if model_id not in models:
            raise ValueError(f"unknown uav model: {model_id}")
        if camera_id not in cameras:
            raise ValueError(f"unknown camera: {camera_id}")
        if (model_id, camera_id) not in edges:
            raise ValueError(f"camera {camera_id} is not compatible with model {model_id}")
        model = models[model_id]
        camera = cameras[camera_id]
        camera_spectra = _spectra(camera)
        if required_spectrum not in camera_spectra:
            mismatches.append(
                SpectrumMismatch(
                    model_id=model_id,
                    camera_id=camera_id,
                    required_spectrum=required_spectrum,
                    camera_spectra=camera_spectra,
                )
            )
            continue
        missing_fields = _missing_fields(model, camera)
        if missing_fields:
            skips.append(Skip(model_id=model_id, camera_id=camera_id, missing=tuple(missing_fields)))
            continue
        runnable.append((board, by_aerodrome[board["aerodrome_id"]], model, camera))
    if not runnable:
        return [], skips, mismatches
    if len(runnable) > MAX_CALLS:
        raise ValueError("at most 16 calls")
    limit = _positive_int(time_limit_s, "time_limit_s")
    input_data_cls, validation_error = _input_api_types()
    shared = {name: scenario[name] for name in _SHARED}
    built: list[Candidate] = []
    for board, aerodrome, model, camera in runnable:
        payload = {
            **shared,
            "takeoff": {"lat": aerodrome["lat"], "lon": aerodrome["lon"]},
            "uav": _flight(model, board["count"]),
            "camera": _optics(camera),
            "solver": _solver_cfg(limit, scenario.get("solver")),
        }
        try:
            data = input_data_cls(**payload)
        except validation_error as exc:
            raise ValueError(_invalid_fields(exc)) from exc
        built.append(
            Candidate(
                aerodrome_id=aerodrome["id"],
                board_id=board["id"],
                model_id=board["model_id"],
                camera_id=board["camera_id"],
                data=data,
            )
        )
    return built, skips, mismatches


def _empty_reason(
    skips: tuple[Skip, ...],
    mismatches: tuple[SpectrumMismatch, ...],
) -> str:
    """No admitted card. A total spectrum miss outranks missing numbers."""
    if mismatches and not skips:
        return _NO_SPECTRUM
    return _NO_RUNNABLE


def _spectra(camera: dict[str, Any]) -> tuple[str, ...]:
    raw = camera.get("spectra")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def _compatibility(
    catalog: dict[str, Any],
    models: dict[str, dict[str, Any]],
    cameras: dict[str, dict[str, Any]],
) -> set[tuple[str, str]]:
    edges = catalog.get("compatibility")
    if not isinstance(edges, list):
        raise ValueError("missing fields: compatibility")
    found: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValueError(f"missing fields: compatibility[{index}]")
        model_id = _text(edge.get("uav_model_id"), f"compatibility[{index}].uav_model_id")
        camera_id = _text(edge.get("camera_id"), f"compatibility[{index}].camera_id")
        if model_id not in models:
            raise ValueError(f"unknown uav model in catalog: {model_id}")
        if camera_id not in cameras:
            raise ValueError(f"unknown camera in catalog: {camera_id}")
        found.add((model_id, camera_id))
    return found


def _index(raw: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError(f"missing fields: {label}")
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: {label}[{index}]")
        row_id = _text(item.get("id"), f"{label}[{index}].id")
        if row_id in indexed:
            raise ValueError(f"duplicate catalog id: {row_id}")
        indexed[row_id] = item
    return indexed


def _missing_fields(model: dict[str, Any], camera: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in _OPTICS:
        value = camera.get(key)
        if key in _PIXELS:
            if not _whole_number(value):
                missing.append(key)
        elif not _number(value):
            missing.append(key)
    if not _number(model.get("airspeed_m_s")):
        missing.append("airspeed_m_s")
    battery = model.get("battery")
    energy = battery.get("energy_wh") if isinstance(battery, dict) else None
    if not _number(energy):
        missing.append("battery.energy_wh")
    for key, _input_name in _OTHER_FLIGHT:
        if not _number(model.get(key)):
            missing.append(key)
    name = model.get("name")
    if not isinstance(name, str) or not name:
        missing.append("name")
    return missing


def _optics(camera: dict[str, Any]) -> dict[str, Any]:
    optics: dict[str, Any] = {}
    for key in _OPTICS:
        value = camera[key]
        optics[key] = int(value) if key in _PIXELS else float(value)
    return optics


def _flight(model: dict[str, Any], count: int) -> dict[str, Any]:
    battery = model["battery"]
    flight = {
        "model": model["name"],
        "count": count,
        "mass_kg": float(model["mass_kg"]),
        "max_flight_time_s": float(model["flight_time_s"]),
        "battery_wh": float(battery["energy_wh"]),
        "v_air_ms": float(model["airspeed_m_s"]),
        "v_vertical_ms": float(model["climb_m_s"]),
        "max_wind_ms": float(model["max_wind_m_s"]),
    }
    present = tuple(key for key in flight if key != "count")
    if present != _FLIGHT:
        raise ValueError("missing fields: " + ", ".join(key for key in _FLIGHT if key not in flight))
    return flight


def _aerodromes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("missing fields: aerodromes")
    if len(raw) > MAX_AERODROMES:
        raise ValueError("at most 4 aerodromes")
    aerodromes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: aerodromes[{index}]")
        aerodrome_id = _text(item.get("id"), f"aerodromes[{index}].id")
        if aerodrome_id in seen:
            raise ValueError(f"duplicate aerodrome: {aerodrome_id}")
        seen.add(aerodrome_id)
        lat = _coord(item.get("lat"), f"aerodromes[{index}].lat")
        lon = _coord(item.get("lon"), f"aerodromes[{index}].lon")
        aerodromes.append({"id": aerodrome_id, "lat": lat, "lon": lon})
    return aerodromes


def _boards(raw: Any, aerodromes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("missing fields: boards")
    known = {item["id"] for item in aerodromes}
    boards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: boards[{index}]")
        board_id = _text(item.get("id"), f"boards[{index}].id")
        if board_id in seen:
            raise ValueError(f"duplicate board: {board_id}")
        seen.add(board_id)
        model_id = _text(item.get("model_id"), f"boards[{index}].model_id")
        camera_id = _text(item.get("camera_id"), f"boards[{index}].camera_id")
        aerodrome_id = _text(item.get("aerodrome_id"), f"boards[{index}].aerodrome_id")
        if aerodrome_id not in known:
            raise ValueError(f"unknown aerodrome: {aerodrome_id}")
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"missing fields: boards[{index}].count")
        boards.append(
            {
                "id": board_id,
                "model_id": model_id,
                "camera_id": camera_id,
                "aerodrome_id": aerodrome_id,
                "count": count,
            }
        )
    return boards


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing fields: {label}")
    return value


def _coord(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    return float(value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _whole_number(value: Any) -> bool:
    if not _number(value):
        return False
    if isinstance(value, float) and not value.is_integer():
        return False
    return True


def _positive_int(value: int | float, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    limit = int(value)
    if limit < 1 or float(value) != limit:
        raise ValueError(f"missing fields: {label}")
    return limit


def _solver_cfg(time_limit_s: int, existing: Any) -> dict[str, Any]:
    """Task time limit. Other ``SolverCfg`` fields stay on Grisha's values."""
    block: dict[str, Any] = {}
    if isinstance(existing, dict):
        for key in ("turn_time_s", "apply_turn_to_base"):
            if key in existing:
                block[key] = existing[key]
    block["time_limit_s"] = time_limit_s
    return block


def _default_core(data: Any, seed: int = 42) -> dict[str, Any]:
    return _run_optimizer()(data, "meta", seed=seed)


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
