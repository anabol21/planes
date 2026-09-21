"""One in-flight compute job on the listener."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path


def default_lock_path() -> Path:
    override = os.environ.get("PLANES_LOCK_PATH", "").strip()
    if override:
        return Path(override)
    for candidate in (
        Path("/run/planes/planes-compute.lock"),
        Path("/var/lock/planes-compute.lock"),
    ):
        directory = candidate.parent
        if directory.is_dir() and os.access(directory, os.W_OK):
            return candidate
    return Path(tempfile.gettempdir()) / "planes-compute.lock"


class JobLock:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_lock_path()
        self._handle = None

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
