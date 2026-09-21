"""Runtime, не точка интеграции.

Stdin is one ComputeRequest. Stdout is one ComputeResponse. Logs go to stderr.
Exit 0 when a response was written.
"""

from __future__ import annotations

import sys

from planes.runtime.pipeline import emit, run


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        response = run(raw)
        sys.stdout.write(emit(response))
        sys.stdout.flush()
    except Exception:
        sys.stderr.write("failed to write ComputeResponse\n")
        return 1
    sys.stderr.write(f"job_id={response.job_id} outcome={response.outcome}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
