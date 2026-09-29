"""Live solve bridge: Grisha contour + isolated Fields2Cover worker.

Routes ``solver.solve`` for geo envelopes through the isolated F2C client,
which spawns the embed-venv worker (ortools 9.9 + fields2cover 2.1.0) with
PYTHONPATH cleared. ``strip_direction_deg`` is ignored; F2C uses
``generateBestSwaths``. Board cameras are checked against
``required_spectrum`` / catalog ``spectra`` before DEM or the worker;
a mismatch returns ``Infeasible`` immediately. When ``dem_file`` is
absent, the bridge acquires a COP30 GeoTIFF via
``ensure_dem_for_iso_scenario`` before the worker.

Full in-process ``mvp_optimizator`` is NOT imported here (sitecustomize/absl).

Paths are env-configurable. Deploy default root is ``/opt/planes-grisha-f2c``;
a checkout uses ``tools/f2c_iso/`` when those files exist.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping


_CATALOG_PATH = Path(__file__).resolve().parent / "catalog" / "fleet_catalog.json"
_NO_SPECTRUM = "no camera covers required spectrum"


def load_fleet_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or _CATALOG_PATH
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fleet catalog must be a JSON object")
    return payload


def _camera_index(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = catalog.get("cameras")
    if not isinstance(rows, list):
        return {}
    found: dict[str, Mapping[str, Any]] = {}
    for item in rows:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            found[item["id"]] = item
    return found


def _spectra(camera: Mapping[str, Any]) -> tuple[str, ...]:
    raw = camera.get("spectra")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str) and item.strip())


def required_spectrum_of(scenario: Mapping[str, Any]) -> str | None:
    for key in ("required_spectrum", "survey_type"):
        raw = scenario.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def spectrum_mismatch_limitations(
    scenario: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return limitation lines when any selected board camera misses the spectrum.

    Prefers refusing the whole job if any board mismatches (same wording as
    the enumeration / geo_mission helpers).
    """
    required = required_spectrum_of(scenario)
    if required is None:
        return ()
    boards = scenario.get("boards")
    if not isinstance(boards, list) or not boards:
        return ()
    cameras = _camera_index(catalog if catalog is not None else load_fleet_catalog())
    notes: list[str] = []
    for board in boards:
        if not isinstance(board, Mapping):
            continue
        camera_id = board.get("camera_id")
        model_id = board.get("model_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            continue
        if not isinstance(model_id, str) or not model_id.strip():
            model_id = "?"
        record = cameras.get(camera_id)
        spectra = _spectra(record) if record is not None else ()
        if required in spectra:
            continue
        listed = ", ".join(spectra) if spectra else "(none)"
        notes.append(
            f"spectrum mismatch model {model_id} camera {camera_id}: "
            f"required {required}, camera spectra {listed}"
        )
    if not notes:
        return ()
    return (_NO_SPECTRUM, *notes)


_DEFAULT_GRISHA_ROOT = "/opt/planes-grisha-f2c"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def grisha_root() -> Path:
    return Path(os.environ.get("PLANES_GRISHA_ROOT", _DEFAULT_GRISHA_ROOT))


def isolated_client_path() -> Path:
    """Resolve ``f2c_isolated_client.py``.

    Order: ``PLANES_F2C_CLIENT``, in-repo ``tools/f2c_iso/``, then
    ``$PLANES_GRISHA_ROOT/tools/`` (deploy layout).
    """
    env = os.environ.get("PLANES_F2C_CLIENT")
    if env:
        return Path(env)
    candidates = (
        _repo_root() / "tools" / "f2c_iso" / "f2c_isolated_client.py",
        grisha_root() / "tools" / "f2c_isolated_client.py",
        grisha_root() / "tools" / "f2c_iso" / "f2c_isolated_client.py",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def isolated_worker_path() -> Path:
    """Resolve ``f2c_isolated_worker.py``.

    Order: ``PLANES_F2C_WORKER``, in-repo ``tools/f2c_iso/``, then
    ``$PLANES_GRISHA_ROOT/tools/`` (deploy layout).
    """
    env = os.environ.get("PLANES_F2C_WORKER")
    if env:
        return Path(env)
    candidates = (
        _repo_root() / "tools" / "f2c_iso" / "f2c_isolated_worker.py",
        grisha_root() / "tools" / "f2c_isolated_worker.py",
        grisha_root() / "tools" / "f2c_iso" / "f2c_isolated_worker.py",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _load_client():
    client_path = isolated_client_path()
    spec = importlib.util.spec_from_file_location("f2c_isolated_client", client_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load isolated client: {client_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def solve_via_isolated_grisha_f2c(problem: Any, deadline: float):
    """Return Solution | Infeasible | TimedOut for one geo envelope."""
    from planes.integration.terrain.iso_acquire import ensure_dem_for_iso_scenario
    from planes.integration.terrain.opentopography import TerrainAcquisitionError
    from planes.runtime.solver import Infeasible, Solution, TimedOut

    remaining = max(1.0, float(deadline) - time.monotonic())
    scenario = copy.deepcopy(problem.scenario)
    if isinstance(scenario.get("survey"), dict):
        # Contract: strip_direction_deg ignored on fields2cover contour.
        scenario["survey"] = {
            k: v for k, v in scenario["survey"].items() if k != "strip_direction_deg"
        }

    spectrum_notes = spectrum_mismatch_limitations(scenario)
    if spectrum_notes:
        return Infeasible(spectrum_notes)

    try:
        scenario, dem_notes = ensure_dem_for_iso_scenario(scenario)
    except TerrainAcquisitionError as exc:
        raise ValueError(f"iso DEM acquisition failed: {exc}") from exc

    request = {
        "contract_version": "v0",
        "job_id": problem.job_id,
        "seed": problem.seed,
        "optimization": {
            "objective": problem.objective,
            "time_limit_seconds": remaining,
        },
        "scenario": scenario,
    }

    client = _load_client()
    raw = client.solve(request, worker=isolated_worker_path(), timeout_s=remaining + 5.0)

    outcome = raw.get("outcome")
    report = raw.get("solver_report") or {}
    limitations = list(report.get("limitations") or [])
    limitations.extend(dem_notes)
    # Prod: do not append internal bridge/iso plumbing into solver_report.limitations.

    if outcome == "feasible":
        plan = raw.get("mission_plan")
        if not isinstance(plan, dict):
            return Infeasible(("bridge: feasible without mission_plan", *limitations))
        # Ensure identity fields for judge / contract consumers.
        plan.setdefault("solver", "grisha_mvp_fields2cover")
        plan.setdefault("decomposition_method", "fields2cover")
        plan.setdefault("engine", "f2c_isolated_generateBestSwaths")
        method = report.get("method") or "grisha_mvp_fields2cover_isolated"
        mission = plan.get("mission") or {}
        criterion = plan.get("criterion") or "min_time"
        if criterion == "min_time":
            objective_value = float(mission.get("mission_time_s") or 0.0)
        else:
            objective_value = float(mission.get("total_flight_time_s") or 0.0)
        return Solution(
            mission_plan=plan,
            method=str(method),
            objective_value=objective_value,
            limitations=tuple(limitations),
        )
    if outcome == "infeasible":
        return Infeasible(tuple(limitations) or ("isolated F2C infeasible",))
    if outcome == "timed_out":
        return TimedOut(tuple(limitations) or ("isolated F2C timed out",))
    err = raw.get("error") or "isolated F2C error"
    # Surface as Infeasible-with-notes via ValueError so pipeline → outcome=error
    raise ValueError(f"grisha_f2c_bridge: {err}")
