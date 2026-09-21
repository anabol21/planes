"""Для агента Гриши.

Deterministic stand-in for the optimization binary.

The listener's CLI spawns this module. A later solver replaces the argv only
(``PLANES_SOLVER_ARGV``). Harness field ``optimization.placeholder_outcome``:

- ``feasible`` (default): exit 0 and a placeholder mission_plan
- ``infeasible``: exit 0, no mission_plan
- ``crash``: non-zero exit
- ``invalid``: exit 0 with non-JSON stdout
- ``sleep``: ignore SIGTERM so the CLI timeout path can SIGKILL the process

The placeholder result is not an optimized mission and is not globally optimal.
"""

from __future__ import annotations

import json
import signal
import sys
import time

from planes.runtime.types import (
    PLACEHOLDER_OUTCOMES,
    dump_response,
    make_response,
    parse_request,
)

_LIMITATION = "Placeholder core is not an optimization result and is not globally optimal."


def _die_with_parent() -> None:
    """Ask Linux to SIGKILL this process if the CLI parent dies."""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        pr_set_pdeathsig = 1
        libc.prctl(pr_set_pdeathsig, signal.SIGKILL)
    except (OSError, AttributeError):
        return


def main() -> int:
    _die_with_parent()
    raw = sys.stdin.buffer.read()
    try:
        request = parse_request(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        sys.stderr.write("placeholder could not read ComputeRequest\n")
        return 2

    mode = request.optimization.placeholder_outcome or "feasible"
    if mode not in PLACEHOLDER_OUTCOMES:
        sys.stderr.write("unknown placeholder_outcome\n")
        return 2
    if mode == "sleep":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(3600)
    if mode == "crash":
        sys.stderr.write("placeholder requested crash\n")
        return 3
    if mode == "invalid":
        sys.stdout.write("not-json\n")
        return 0

    mission = None
    if mode == "feasible":
        mission = {
            "kind": "placeholder",
            "job_id": request.job_id,
            "seed": request.seed,
        }
    response = make_response(
        job_id=request.job_id,
        outcome=mode,
        method="placeholder",
        objective=request.optimization.objective,
        runtime_seconds=0.0,
        seed=request.seed,
        limitations=[_LIMITATION],
        mission_plan=mission,
    )
    sys.stdout.write(dump_response(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
