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

from planner.models import Criterion, DecompositionMethod, Params, Wind
from planner.solver.pipeline import _angles_to_try, _uses_auto_f2c


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
        self.assertTrue(_uses_auto_f2c(mission))
        self.assertEqual(_angles_to_try(mission), [0.0])

    def test_empty_fields2cover_is_one_dummy_pass(self) -> None:
        params = _params(
            angles_deg=[],
            decomposition=DecompositionMethod.FIELDS2COVER,
        )

        class Mission:
            pass

        mission = Mission()
        mission.params = params
        self.assertEqual(_angles_to_try(mission), [0.0])

    def test_trapezoid_keeps_supplied_angles(self) -> None:
        params = _params(
            angles_deg=[15.0, 75.0],
            decomposition=DecompositionMethod.TRAPEZOID,
        )

        class Mission:
            pass

        mission = Mission()
        mission.params = params
        self.assertFalse(_uses_auto_f2c(mission))
        self.assertEqual(_angles_to_try(mission), [15.0, 75.0])


class GenerateF2CPathTest(unittest.TestCase):
    def test_fields2cover_calls_backend_and_ignores_angle(self) -> None:
        from shapely.geometry import LineString

        from planner.geometry import generate as generate_mod
        from planner.models import Area

        area = Area(
            id="survey-1",
            name="survey-1",
            polygon={
                "type": "Polygon",
                "coordinates": [[
                    [37.600, 55.750],
                    [37.608, 55.750],
                    [37.608, 55.754],
                    [37.600, 55.754],
                    [37.600, 55.750],
                ]],
            },
        )
        camera = {
            "specs": {
                "general": {
                    "max_resolution": "6000x4000",
                    "sensor_size": "23.5x15.6",
                },
                "performance": {"focal_length": "20"},
            }
        }
        seen: list[tuple[float, float]] = []

        def fake_lines(poly_m, spacing_m, headland_width_m=0.0):
            del poly_m, headland_width_m
            seen.append((spacing_m, 90.0))
            return [LineString([(0.0, 0.0), (40.0, 0.0)])]

        with (
            patch.object(generate_mod, "_use_fields2cover", return_value=True),
            patch.object(generate_mod, "_generate_lines_f2c", side_effect=fake_lines),
        ):
            swaths, _h = generate_mod.generate_swaths_for_area(
                area=area,
                obstacles=[],
                angle_deg=90.0,
                gsd_cm_per_px=3.0,
                camera=camera,
                decomposition="fields2cover",
            )
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(len(swaths), 1)


if __name__ == "__main__":
    unittest.main()
