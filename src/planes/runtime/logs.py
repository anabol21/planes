"""Runtime, не точка интеграции.

Job logs. Token values and Authorization headers are never written.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_MAX_STDERR = 16_384


def redact(text: str) -> str:
    token = os.environ.get("COMPUTE_TOKEN", "")
    if token:
        text = text.replace(token, "[redacted]")
    return _BEARER.sub("Bearer [redacted]", text)


def log_directory() -> Path:
    preferred = Path("/var/log/planes")
    if preferred.is_dir() and os.access(preferred, os.W_OK):
        return preferred
    fallback = Path(tempfile.gettempdir()) / "planes-logs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def record(job_id: str, summary: str, stderr_text: str = "") -> str:
    """Append a redacted job record and mirror it to stderr. Returns the path."""
    path = log_directory() / f"{job_id}.log"
    chunks = [redact(summary).rstrip("\n")]
    cleaned = redact(stderr_text)[:_MAX_STDERR].rstrip("\n")
    if cleaned:
        chunks.append(cleaned)
    payload = "\n".join(chunks) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
    sys.stderr.write(payload)
    return str(path)
