"""Полная диагностика окружения F2C.

Проверяет:
  1. Пути — где физически лежит planner и f2c_backend.
  2. Импорт fields2cover напрямую и через backend.
  3. _f2c_module и _f2c_import_error в backend.
  4. Кэш _f2c_import_attempted.
  5. LD_LIBRARY_PATH и ldconfig.
  6. Проверку реальной генерации полос через backend.

Запуск:
    python3 scripts/diagnose_f2c_env.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _hdr(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _ok(label: str, value) -> None:
    print(f"  [OK]   {label}: {value}")


def _fail(label: str, value) -> None:
    print(f"  [FAIL] {label}: {value}")


def _info(label: str, value) -> None:
    print(f"  [INFO] {label}: {value}")


# ============================================================
# 1. Пути
# ============================================================

def check_paths() -> None:
    _hdr("1. Пути")

    # sys.path
    print("sys.path (первые 5):")
    for p in sys.path[:5]:
        print(f"    {p}")

    # Где planner
    try:
        import planner
        _info("planner.__file__", planner.__file__)
        planner_path = Path(planner.__file__).resolve().parent
        _info("planner dir", planner_path)
    except Exception as e:
        _fail("import planner", f"{type(e).__name__}: {e}")
        return

    # Где f2c_backend
    try:
        from planner.geometry import f2c_backend
        fb_path = Path(f2c_backend.__file__).resolve()
        _info("f2c_backend.__file__", fb_path)

        # Сравниваем с /app/src
        expected = Path("/app/src/planner/geometry/f2c_backend.py").resolve()
        if fb_path == expected:
            _ok("путь к f2c_backend", "совпадает с /app/src")
        else:
            _fail(
                "путь к f2c_backend",
                f"НЕ /app/src! Ожидалось {expected}, получено {fb_path}",
            )
            _fail(
                "проблема",
                "planner установлен в site-packages и перекрывает /app/src. "
                "Решение: pip uninstall -y planner, "
                "или убери site-packages из sys.path",
            )
    except Exception as e:
        _fail("import f2c_backend", f"{type(e).__name__}: {e}")


# ============================================================
# 2. Импорт fields2cover напрямую
# ============================================================

def check_direct_import() -> None:
    _hdr("2. Прямой импорт fields2cover")

    try:
        import fields2cover
        _ok("import fields2cover", fields2cover.__version__)
        _info("fields2cover.__file__", fields2cover.__file__)
    except ImportError as e:
        _fail("import fields2cover", f"ImportError: {e}")
    except OSError as e:
        _fail("import fields2cover", f"OSError (нативный .so): {e}")
    except Exception as e:
        _fail("import fields2cover", f"{type(e).__name__}: {e}")


# ============================================================
# 3. Backend: is_available, get_import_error, кэш
# ============================================================

def check_backend_state() -> None:
    _hdr("3. Состояние f2c_backend")

    try:
        from planner.geometry import f2c_backend as fb
    except Exception as e:
        _fail("import f2c_backend", f"{type(e).__name__}: {e}")
        return

    # Кэш
    attempted = getattr(fb, "_f2c_import_attempted", "<нет атрибута>")
    err = getattr(fb, "_f2c_import_error", "<нет атрибута>")
    mod = getattr(fb, "_f2c_module", "<нет атрибута>")

    _info("_f2c_import_attempted", attempted)
    _info("_f2c_import_error", repr(err))
    _info("_f2c_module", type(mod).__name__ if mod else mod)

    # is_available
    try:
        avail = fb.is_available()
        if avail:
            _ok("is_available()", True)
        else:
            _fail("is_available()", False)
    except Exception as e:
        _fail("is_available()", f"{type(e).__name__}: {e}")

    # get_import_error
    try:
        err2 = fb.get_import_error()
        _info("get_import_error()", repr(err2))
    except Exception as e:
        _fail("get_import_error()", f"{type(e).__name__}: {e}")

    # После is_available — обновилось ли состояние
    _info("_f2c_import_attempted (после)",
          getattr(fb, "_f2c_import_attempted", "?"))
    _info("_f2c_module (после)",
          type(getattr(fb, "_f2c_module", None)).__name__)


# ============================================================
# 4. LD_LIBRARY_PATH и ldconfig
# ============================================================

def check_ld_path() -> None:
    _hdr("4. LD_LIBRARY_PATH и ldconfig")

    ld_path = os.environ.get("LD_LIBRARY_PATH", "<не задан>")
    _info("LD_LIBRARY_PATH", ld_path)

    # Проверка libortools
    try:
        result = subprocess.run(
            ["ldconfig", "-p"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [
            l for l in result.stdout.splitlines()
            if "ortools" in l.lower()
        ]
        if lines:
            _ok("ldconfig", f"нашёл {len(lines)} записей:")
            for l in lines[:3]:
                print(f"          {l.strip()}")
        else:
            _fail("ldconfig", "libortools не найден")
    except Exception as e:
        _fail("ldconfig -p", f"{type(e).__name__}: {e}")

    # Физическое наличие
    lib_path = Path("/usr/local/lib/libortools.so.9")
    if lib_path.exists():
        size_mb = lib_path.stat().st_size / (1024 * 1024)
        _ok("libortools.so.9", f"{size_mb:.1f} МБ")
        _info("  symlink target", os.readlink(lib_path) if lib_path.is_symlink() else "не symlink")
    else:
        _fail("libortools.so.9", "файл не найден в /usr/local/lib/")

    # ctypes — грузится ли библиотека
    try:
        import ctypes
        ctypes.CDLL("libortools.so.9")
        _ok("ctypes.CDLL('libortools.so.9')", "загружена")
    except OSError as e:
        _fail("ctypes.CDLL", f"OSError: {e}")
    except Exception as e:
        _fail("ctypes.CDLL", f"{type(e).__name__}: {e}")


# ============================================================
# 5. Реальная генерация полос через backend
# ============================================================

def check_real_generation() -> None:
    _hdr("5. Реальная генерация полос через backend")

    try:
        from shapely.geometry import Polygon
        from planner.geometry.f2c_backend import generate_swaths_f2c

        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        _info("полигон", "100×100 м")

        import time
        t0 = time.time()
        lines = generate_swaths_f2c(poly, 20.0)
        dt = time.time() - t0

        if lines:
            _ok("generate_swaths_f2c", f"{len(lines)} полос за {dt:.3f}s")
            if lines:
                _info("  первая линия", lines[0].wkt[:60])
        else:
            _fail("generate_swaths_f2c", "0 полос — F2C не работает")

    except Exception as e:
        import traceback
        _fail("generate_swaths_f2c", f"{type(e).__name__}: {e}")
        traceback.print_exc()


# ============================================================
# 6. Что видит pipeline._angles_to_try
# ============================================================

def check_angles_to_try() -> None:
    _hdr("6. Что решает _angles_to_try")

    try:
        from planner.solver.pipeline import _angles_to_try
        from planner.models import (
            MissionInput, Params, Wind, Area, VPP, UAVConfig,
        )

        p = Params(
            gsd_cm_per_px=3.0,
            wind=Wind(speed_mps=5.0, direction_deg=90.0),
            decomposition="fields2cover",
        )
        mission = MissionInput(
            areas=[Area(
                id="test", name="test",
                polygon={
                    "type": "Polygon",
                    "coordinates": [[
                        [37.62, 55.75], [37.63, 55.75],
                        [37.63, 55.755], [37.62, 55.755],
                        [37.62, 55.75],
                    ]],
                },
            )],
            vpps=[VPP(id="v1", lat=55.75, lon=37.62)],
            uavs=[UAVConfig(
                id="u1", model="gemini", camera_id="pf1b",
                vpp_id="v1",
            )],
            params=p,
        )

        angles = _angles_to_try(mission)
        _ok("_angles_to_try", angles)

    except Exception as e:
        import traceback
        _fail("_angles_to_try", f"{type(e).__name__}: {e}")
        traceback.print_exc()


# ============================================================
# Main
# ============================================================

def main() -> int:
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " F2C ENVIRONMENT DIAGNOSTIC ".center(68) + "║")
    print("╚" + "═" * 68 + "╝")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  cwd:    {os.getcwd()}")

    check_paths()
    check_direct_import()
    check_backend_state()
    check_ld_path()
    check_real_generation()
    check_angles_to_try()

    _hdr("ИТОГ")
    print("Если все пункты [OK] — F2C работает.")
    print("Если где-то [FAIL] — скинь вывод этого блока.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())