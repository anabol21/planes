"""Params and planner angle helpers for the auto-F2C contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError


_CORE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "itog_model"
    / "mvp_optimizator"
    / "src"
)
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import importlib.util

from planner.models import Criterion, DecompositionMethod, Params, Wind


def _load_angles():
    path = _CORE / "planner" / "solver" / "angles.py"
    spec = importlib.util.spec_from_file_location("planner_solver_angles", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_angles = _load_angles()
angles_to_try = _angles.angles_to_try
uses_auto_f2c = _angles.uses_auto_f2c


def _wind() -> Wind:
    return Wind(speed_mps=1.0, direction_deg=90.0)


def _params(**kwargs) -> Params:
    body = {
        "gsd_cm_per_px": 3.0,
        "wind": _wind(),
        "optimization_criterion": Criterion.MIN_TIME,
    }
    body.update(kwargs)
    return Params(**body)


class ParamsAutoAngleTest(unittest.TestCase):
    def test_empty_angles_allowed_for_fields2cover(self) -> None:
        params = _params(angles_deg=[], decomposition=DecompositionMethod.FIELDS2COVER)
        self.assertEqual(params.angles_deg, [])
        params_none = _params(
            angles_deg=None,
            decomposition=DecompositionMethod.FIELDS2COVER,
        )
        self.assertEqual(params_none.angles_deg, [])

    def test_empty_angles_allowed_for_auto(self) -> None:
        params = _params(angles_deg=[], decomposition=DecompositionMethod.AUTO)
        self.assertEqual(params.angles_deg, [])

    def test_empty_angles_rejected_for_trapezoid(self) -> None:
        with self.assertRaises(ValidationError):
            _params(angles_deg=[], decomposition=DecompositionMethod.TRAPEZOID)

    def test_nonempty_angles_still_work(self) -> None:
        params = _params(angles_deg=[0.0, 90.0])
        self.assertEqual(params.angles_deg, [0.0, 90.0])


class AnglesToTryTest(unittest.TestCase):
    def test_fields2cover_ignores_request_angles(self) -> None:
        params = _params(
            angles_deg=[45.0],
            decomposition=DecompositionMethod.FIELDS2COVER,
        )

        class Mission:
            pass

        mission = Mission()
        mission.params = params
        self.assertTrue(uses_auto_f2c(mission))
        self.assertEqual(angles_to_try(mission), [0.0])

    def test_empty_fields2cover_is_one_dummy_pass(self) -> None:
        params = _params(
            angles_deg=[],
            decomposition=DecompositionMethod.FIELDS2COVER,
        )

        class Mission:
            pass

        mission = Mission()
        mission.params = params
        self.assertEqual(angles_to_try(mission), [0.0])

    def test_trapezoid_keeps_supplied_angles(self) -> None:
        params = _params(
            angles_deg=[15.0, 75.0],
            decomposition=DecompositionMethod.TRAPEZOID,
        )

        class Mission:
            pass

        mission = Mission()
        mission.params = params
        self.assertFalse(uses_auto_f2c(mission))
        self.assertEqual(angles_to_try(mission), [15.0, 75.0])


def _load_f2c_backend():
    import types

    logging_mod = types.ModuleType("planner.utils.logging")

    def _noop(*_args, **_kwargs):
        return None

    logging_mod.log_error = _noop
    logging_mod.log_info = _noop
    logging_mod.log_warn = _noop
    utils_mod = types.ModuleType("planner.utils")
    utils_mod.logging = logging_mod
    sys.modules.setdefault("planner.utils", utils_mod)
    sys.modules["planner.utils.logging"] = logging_mod
    path = _CORE / "planner" / "geometry" / "f2c_backend.py"
    spec = importlib.util.spec_from_file_location("planner_geometry_f2c_backend", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class F2CBackendAutoAngleTest(unittest.TestCase):
    def test_backend_calls_generate_best_swaths_not_fixed_angle(self) -> None:
        from shapely.geometry import LineString, Polygon

        backend = _load_f2c_backend()

        calls: list[str] = []

        class FakePoint:
            def __init__(self, x: float, y: float) -> None:
                self._x = x
                self._y = y

            def getX(self) -> float:
                return self._x

            def getY(self) -> float:
                return self._y

        class FakeSwath:
            def startPoint(self) -> FakePoint:
                return FakePoint(0.0, 0.0)

            def endPoint(self) -> FakePoint:
                return FakePoint(12.0, 0.0)

        class FakeSwaths:
            def sizeTotal(self) -> int:
                return 1

            def getSwath(self, index: int) -> FakeSwath:
                del index
                return FakeSwath()

        class FakeBF:
            def generateBestSwaths(self, obj, spacing, cells):
                del cells
                calls.append(f"best:{type(obj).__name__}:{spacing}")
                return FakeSwaths()

            def generateSwaths(self, *args, **kwargs):
                del args, kwargs
                raise AssertionError("generateSwaths must not run on the F2C path")

        class FakeF2C:
            OBJ_NSwathModified = type("OBJ_NSwathModified", (), {})
            OBJ_NSwath = type("OBJ_NSwath", (), {})
            OBJ_SwathLength = type("OBJ_SwathLength", (), {})
            SG_BruteForce = FakeBF
            Point = lambda self_or_x=None, y=None, *a, **k: FakePoint(0, 0)
            VectorPoint = list
            LinearRing = object
            Cell = object
            Cells = object

        poly = Polygon([(0, 0), (40, 0), (40, 20), (0, 20)])
        with (
            patch.object(backend, "_load_f2c", return_value=FakeF2C),
            patch.object(backend, "_shapely_to_f2c_cells", return_value=object()),
        ):
            lines = backend._generate_for_single_polygon(poly, 15.0, 0.0)
        self.assertEqual(calls, ["best:OBJ_NSwathModified:15.0"])
        self.assertEqual(len(lines), 1)
        self.assertIsInstance(lines[0], LineString)


if __name__ == "__main__":
    unittest.main()
