#!/usr/bin/env python3
"""Client that spawns the isolated F2C worker in a clean subprocess.

Safe to call from a parent that has Grisha mvp_optimizator/src on PYTHONPATH
(and would load sitecustomize in-process). The worker runs under the throwaway
embed venv with PYTHONPATH cleared and PYTHONNOUSERSITE=1, so sitecustomize
never loads there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_DEFAULT_WORKER = _HERE / "f2c_isolated_worker.py"
_DEFAULT_GRISHA_ROOT = "/opt/planes-grisha-f2c"


def grisha_root() -> Path:
    return Path(os.environ.get("PLANES_GRISHA_ROOT", _DEFAULT_GRISHA_ROOT))


def default_worker_path() -> Path:
    env = os.environ.get("PLANES_F2C_WORKER") or os.environ.get("F2C_ISO_WORKER")
    if env:
        return Path(env)
    return _DEFAULT_WORKER


def embed_python() -> Path:
    """Locate the isolated embed interpreter (ortools 9.9 + fields2cover 2.1.0)."""
    root = grisha_root()
    candidates = [
        Path(os.environ.get("F2C_EMBED_PYTHON", "")),
        root / ".venv-f2c-embed" / "bin" / "python",
        root / ".venv-f2c-embed" / "bin" / "python3",
        Path(_DEFAULT_GRISHA_ROOT) / ".venv-f2c-embed" / "bin" / "python",
        Path(_DEFAULT_GRISHA_ROOT) / ".venv-f2c-embed" / "bin" / "python3",
    ]
    for path in candidates:
        if path and path.is_file():
            return path
    raise FileNotFoundError(
        "embed python not found; set F2C_EMBED_PYTHON or PLANES_GRISHA_ROOT "
        f"(default {_DEFAULT_GRISHA_ROOT}/.venv-f2c-embed)"
    )


def clean_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Strip PYTHONPATH / PYTHONHOME pollution; force no user site."""
    env = dict(base if base is not None else os.environ)
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONSAFEPATH",
    ):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Keep locale for JSON unicode
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    return env


def solve(
    request: dict[str, Any],
    *,
    worker: Path | None = None,
    python_bin: Path | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Spawn isolated worker; return parsed JSON response."""
    worker = worker or default_worker_path()
    if not worker.is_file():
        raise FileNotFoundError(f"worker not found: {worker}")
    py = python_bin or embed_python()
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(py), str(worker)],
        input=payload,
        capture_output=True,
        timeout=timeout_s,
        env=clean_env(),
        cwd=str(worker.parent),
    )
    wall = time.perf_counter() - t0
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if not stdout.strip():
        return {
            "outcome": "error",
            "error": "worker produced no stdout",
            "returncode": proc.returncode,
            "stderr": stderr[-4000:],
            "client_wall_s": wall,
            "embed_python": str(py),
        }
    try:
        resp = json.loads(stdout.splitlines()[-1] if stdout.strip() else "{}")
    except json.JSONDecodeError as exc:
        return {
            "outcome": "error",
            "error": f"worker JSON decode failed: {exc}",
            "stdout_tail": stdout[-2000:],
            "stderr": stderr[-2000:],
            "returncode": proc.returncode,
            "client_wall_s": wall,
        }
    if isinstance(resp, dict):
        resp.setdefault("client_wall_s", wall)
        resp.setdefault("embed_python", str(py))
        if proc.returncode not in (0, 2) and resp.get("outcome") not in (
            "feasible",
            "infeasible",
            "timed_out",
            "error",
        ):
            resp["returncode"] = proc.returncode
            resp["stderr"] = stderr[-2000:]
    return resp


def smoke_from_polluted_parent() -> dict[str, Any]:
    """Prove isolation: parent has mvp on PYTHONPATH; worker must still import f2c."""
    root = grisha_root()
    mvp = root / "src" / "planes" / "model" / "itog_model" / "mvp_optimizator" / "src"
    if not mvp.is_dir():
        mvp = Path("/opt/planes/src/planes/model/itog_model/mvp_optimizator/src")
    parent_path = os.environ.get("PYTHONPATH", "")
    polluted = str(mvp) if mvp.is_dir() else "/tmp/fake_mvp_src_for_smoke"
    os.environ["PYTHONPATH"] = polluted + (os.pathsep + parent_path if parent_path else "")
    parent_info = {
        "parent_python": sys.executable,
        "parent_PYTHONPATH": os.environ["PYTHONPATH"],
        "parent_sitecustomize_loaded": "sitecustomize" in sys.modules,
        "mvp_dir_exists": mvp.is_dir(),
    }
    py = embed_python()
    worker = default_worker_path()
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(py), str(worker), "--self-check"],
        capture_output=True,
        timeout=60,
        env=clean_env(),  # explicitly NOT inheriting polluted PYTHONPATH
        cwd=str(worker.parent),
    )
    wall = time.perf_counter() - t0
    stdout = proc.stdout.decode("utf-8", errors="replace")
    try:
        body = json.loads(stdout.splitlines()[-1]) if stdout.strip() else {}
    except json.JSONDecodeError:
        body = {
            "outcome": "error",
            "error": "smoke JSON decode failed",
            "stdout_tail": stdout[-2000:],
            "stderr": proc.stderr.decode("utf-8", errors="replace")[-2000:],
        }
    return {
        "parent": parent_info,
        "worker": body,
        "smoke_wall_s": wall,
        "returncode": proc.returncode,
        "ok": body.get("outcome") == "feasible"
        and not (body.get("isolation") or {}).get("grisha_sitecustomize", True)
        and not (body.get("isolation") or {}).get("mvp_on_path", True)
        and (body.get("isolation") or {}).get("fields2cover_version") == "2.1.0",
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", "-f", help="Request JSON")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--self-check-worker", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        result = smoke_from_polluted_parent()
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0 if result.get("ok") else 1
    if args.self_check_worker:
        py = embed_python()
        worker = default_worker_path()
        proc = subprocess.run(
            [str(py), str(worker), "--self-check"],
            capture_output=True,
            timeout=60,
            env=clean_env(),
            cwd=str(worker.parent),
        )
        sys.stdout.write(proc.stdout.decode())
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode())
        return proc.returncode
    if not args.file:
        ap.error("need --file, --smoke, or --self-check-worker")
    req = json.loads(Path(args.file).read_text(encoding="utf-8"))
    resp = solve(req)
    json.dump(resp, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if resp.get("outcome") == "feasible" else 1


if __name__ == "__main__":
    raise SystemExit(main())
