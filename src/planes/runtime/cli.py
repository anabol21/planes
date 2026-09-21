"""Per-job compute CLI spawned by the VPS listener.

    python -m planes.runtime.cli solve --request <file|-> --timeout-seconds <N>

Stdout is one ComputeResponse JSON document. Logs go to stderr and a job file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from planes.runtime.runner import dumps, execute
from planes.runtime.types import make_response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planes.runtime.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    solve = sub.add_parser("solve")
    solve.add_argument("--request", required=True, help="Request JSON file, or - for stdin")
    solve.add_argument("--timeout-seconds", required=True, type=float)
    args = parser.parse_args(argv)
    if args.command != "solve":
        parser.error("unknown command")
    try:
        raw = _read_request(args.request)
    except OSError:
        sys.stdout.write(
            dumps(
                make_response(
                    job_id="unknown",
                    outcome="error",
                    method="runtime-wrapper",
                    objective="",
                    runtime_seconds=0.0,
                    seed=0,
                    limitations=["Request file is not readable."],
                )
            )
        )
        return 0
    sys.stdout.write(dumps(execute(raw, args.timeout_seconds)))
    return 0


def _read_request(spec: str) -> bytes:
    if spec == "-":
        return sys.stdin.buffer.read()
    return Path(spec).read_bytes()


if __name__ == "__main__":
    sys.exit(main())
