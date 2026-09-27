"""Preload correct libortools for Python ortools.

Python ortools and Fields2Cover ship DIFFERENT libortools.so.9.
ldconfig gives Python-ortools the C++ one, symbols don't match.
Preload the right one via ctypes.CDLL before ortools imports.
"""

from __future__ import annotations

import ctypes
import site
from pathlib import Path


def _preload_pip_ortools_lib() -> None:
    candidates = []
    try:
        site_dirs = list(site.getsitepackages())
        user_site = site.getusersitepackages()
        if user_site:
            site_dirs.append(user_site)
    except Exception:
        site_dirs = []

    for site_dir in site_dirs:
        libs_dir = Path(site_dir) / "ortools" / ".libs"
        if not libs_dir.is_dir():
            continue
        for name in ("libortools.so.9", "libortools.so"):
            lib_path = libs_dir / name
            if lib_path.exists():
                candidates.append(lib_path)

    for lib_path in candidates:
        try:
            ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
            return
        except OSError:
            continue


_preload_pip_ortools_lib()