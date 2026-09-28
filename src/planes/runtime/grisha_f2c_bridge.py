"""Live solve bridge: Grisha contour + isolated Fields2Cover worker.

Routes ``solver.solve`` for geo envelopes through the isolated F2C client,
which spawns the embed-venv worker (ortools 9.9 + fields2cover 2.1.0) with
PYTHONPATH cleared. ``strip_direction_deg`` is ignored; F2C uses
``generateBestSwaths``.

Full in-process ``mvp_optimizator`` is NOT imported here (sitecustomize/absl).

Paths are env-configurable. Deploy default root is ``/opt/planes-grisha-f2c``;
a checkout uses ``tools/f2c_iso/`` when those files exist.
"""

from __future__ import annotations

import copy
import importlib.util
import os
import time
from pathlib import Path
from typing import Any

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
    from planes.runtime.solver import Infeasible, Solution, TimedOut

    remaining = max(1.0, float(deadline) - time.monotonic())
    scenario = copy.deepcopy(problem.scenario)
    if isinstance(scenario.get("survey"), dict):
        # Contract: strip_direction_deg ignored on fields2cover contour.
        scenario["survey"] = {
            k: v for k, v in scenario["survey"].items() if k != "strip_direction_deg"
        }

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
    limitations.append("live path: grisha_f2c_bridge → f2c_isolated_worker (generateBestSwaths)")
    if raw.get("isolation"):
        iso = raw["isolation"]
        limitations.append(
            f"iso f2c={iso.get('fields2cover_version')} mvp_on_path={iso.get('mvp_on_path')} "
            f"grisha_sitecustomize={iso.get('grisha_sitecustomize')}"
        )

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
