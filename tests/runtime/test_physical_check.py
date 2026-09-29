"""Diagnostic codes read a finished plan. They do not rebuild a route."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from planes.runtime.physical_check import annotate_result, code_line, limitation_lines
from planes.runtime.solver import Infeasible, Solution, TimedOut


_TIME_LIMIT = "solver stopped at the time limit"


_BOARD = {
    "boards": [
        {
            "id": "БВС 1",
            "model_id": "geoscan-gemini",
            "camera_id": "geoscan-pf1b",
            "aerodrome_id": "аэродром 1",
            "count": 1,
        }
    ]
}


def _point(lon: float, lat: float, alt: float | None = 200.0) -> dict:
    return {"lon": lon, "lat": lat, "alt_m": alt}


def _plan(waypoints: list[dict], zones: list[dict] | None = None) -> dict:
    return {
        "routes": [
            {
                "uav_id": "БВС 1",
                "vpp_id": "аэродром 1",
                "flight_index": 0,
                "waypoints": waypoints,
            }
        ],
        "constraint_polygons": zones or [],
    }


def _zone(ring: list[list[float]], text: str | None) -> dict:
    return {"ring": ring, "name": "зона", "type": "restricted", "altitudes_text": text}


def _box(west: float, south: float, east: float, north: float) -> list[list[float]]:
    return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]


class PhysicalCheckTest(unittest.TestCase):
    def test_each_code_and_a_valid_plan_has_none(self) -> None:
        endurance = limitation_lines(
            plan=_plan([_point(37.6, 55.0), _point(37.6, 55.5)]),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertIn(code_line("PHYS-ENDURANCE"), endurance)

        vpp = limitation_lines(
            plan=_plan(
                [_point(37.60, 55.75), _point(37.70, 55.75)],
                [_zone(_box(37.59, 55.74, 37.61, 55.76), "от 0 м AMSL до 5000 м AMSL")],
            ),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertIn(code_line("PHYS-VPP-INSIDE"), vpp)
        self.assertFalse(any(line.startswith("PHYS-AIRSPACE") for line in vpp))

        air = limitation_lines(
            plan=_plan(
                [_point(37.50, 55.75), _point(37.605, 55.755), _point(37.70, 55.75)],
                [_zone(_box(37.60, 55.75, 37.61, 55.76), "от 0 м AMSL до 5000 м AMSL")],
            ),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertIn(code_line("PHYS-AIRSPACE"), air)
        self.assertNotIn(code_line("PHYS-VPP-INSIDE"), air)

        dem = limitation_lines(
            plan=_plan([_point(37.60, 55.75, None), _point(37.601, 55.75, None)]),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertEqual(dem, (code_line("PHYS-DEM"),))

        timeout = limitation_lines(
            plan=None,
            scenario={},
            limitations=(_TIME_LIMIT,),
            outcome="timed_out",
        )
        self.assertEqual(timeout, (code_line("PHYS-TIMEOUT"),))

        missing = limitation_lines(
            plan=None,
            scenario={},
            limitations=("No valid candidates found",),
            outcome="infeasible",
        )
        self.assertEqual(missing, (code_line("PHYS-NO-PLAN"),))

        valid = _plan(
            [_point(37.600, 55.750), _point(37.601, 55.750)],
            [
                _zone(_box(37.59, 55.74, 37.61, 55.76), "от 9000 м AMSL до 10000 м AMSL"),
                _zone(_box(10.0, 10.0, 10.1, 10.1), "абракадабра высоты"),
            ],
        )
        snapshot = json.dumps(valid)
        quiet = limitation_lines(
            plan=valid,
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertEqual(quiet, ())
        self.assertEqual(json.dumps(valid), snapshot)

    def test_unknown_altitude_is_named_only_when_the_plan_already_enters(self) -> None:
        missed = limitation_lines(
            plan=_plan(
                [_point(37.60, 55.75), _point(37.601, 55.75)],
                [_zone(_box(10.0, 10.0, 10.1, 10.1), "абракадабра высоты")],
            ),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertEqual(missed, ())
        self.assertFalse(any("Неразобранный" in line for line in missed))

        entered = limitation_lines(
            plan=_plan(
                [_point(37.50, 55.75), _point(37.605, 55.755), _point(37.70, 55.75)],
                [_zone(_box(37.60, 55.75, 37.61, 55.76), "абракадабра высоты")],
            ),
            scenario=_BOARD,
            limitations=(),
            outcome="feasible",
        )
        self.assertTrue(any(line.startswith("PHYS-AIRSPACE") and "Неразобранный" in line for line in entered))

    def test_annotate_keeps_the_plan_object(self) -> None:
        plan = _plan([_point(37.60, 55.75), _point(37.601, 55.75)])
        result = annotate_result(
            Solution(mission_plan=plan, method="pipeline", objective_value=1.0, limitations=()),
            _BOARD,
        )
        self.assertIs(result.mission_plan, plan)
        self.assertIsInstance(annotate_result(Infeasible(("No valid candidates found",)), {}), Infeasible)
        timed = annotate_result(TimedOut((_TIME_LIMIT,)), {})
        self.assertIsInstance(timed, TimedOut)
        self.assertIn(code_line("PHYS-TIMEOUT"), timed.limitations)

    def test_checker_does_not_call_the_solver(self) -> None:
        source = Path(__file__).resolve().parents[2] / "src" / "planes" / "runtime" / "physical_check.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("fields2cover", text)
        self.assertNotIn("_detour", text)
        self.assertNotIn("acquire_terrain", text)


if __name__ == "__main__":
    unittest.main()
