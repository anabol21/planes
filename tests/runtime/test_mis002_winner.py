"""Winner selection stays on the enumeration module.

The live envelope with aerodromes and boards calls the geo core. These cases
cover ``select_winner``. A one-card scenario is rejected before gibrid.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from planes.runtime.enumeration import Attempt, is_outer_scenario, select_winner
from planes.runtime.solver import Problem, TimedOut, solve

_INPUT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "basic_model"
    / "gibrid-optimizer"
    / "data"
    / "input.json"
)


def _plan(
    mission_time: float,
    flight_time: float,
    status: str = "optimal",
    criterion: str = "min_time",
) -> dict:
    return {
        "status": status,
        "criterion": criterion,
        "solver": "milp",
        "mission": {
            "mission_time_s": mission_time,
            "total_flight_time_s": flight_time,
            "uav_used": 1,
        },
        "routes": [],
        "strips": [],
        "validation": {},
    }


def _attempt(
    aerodrome_id: str,
    board_id: str,
    model_id: str,
    camera_id: str,
    mission_time: float,
    flight_time: float,
    status: str = "optimal",
    criterion: str = "min_time",
) -> Attempt:
    return Attempt(
        aerodrome_id=aerodrome_id,
        board_id=board_id,
        model_id=model_id,
        camera_id=camera_id,
        data=None,
        result=_plan(mission_time, flight_time, status, criterion),
    )


class WinnerSelectionTest(unittest.TestCase):
    def test_min_time_keeps_the_shorter_mission(self) -> None:
        slow = _attempt("a-slow", "b-slow", "m-slow", "c-slow", 20.0, 5.0)
        fast = _attempt("a-fast", "b-fast", "m-fast", "c-fast", 9.0, 30.0)
        winner = select_winner((slow, fast), "min_time")
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner.objective_value, 9.0)
        self.assertEqual(winner.aerodrome_id, "a-fast")
        self.assertEqual(winner.board_id, "b-fast")
        self.assertEqual(winner.model_id, "m-fast")
        self.assertEqual(winner.camera_id, "c-fast")
        self.assertEqual(winner.result["mission"]["mission_time_s"], 9.0)

    def test_min_flight_hours_reads_total_flight_time(self) -> None:
        slow = _attempt("a-slow", "b-slow", "m-slow", "c-slow", 20.0, 5.0, criterion="min_flight_hours")
        fast = _attempt("a-fast", "b-fast", "m-fast", "c-fast", 9.0, 30.0, criterion="min_flight_hours")
        winner = select_winner((slow, fast), "min_flight_hours")
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner.objective_value, 5.0)
        self.assertEqual(winner.aerodrome_id, "a-slow")
        self.assertEqual(winner.board_id, "b-slow")

    def test_tie_keeps_the_earlier_call(self) -> None:
        first = _attempt("a1", "b1", "m1", "c1", 9.0, 9.0)
        second = _attempt("a2", "b2", "m2", "c2", 9.0, 9.0)
        winner = select_winner((first, second), "min_time")
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner.aerodrome_id, "a1")
        self.assertEqual(winner.board_id, "b1")

    def test_empty_attempts_have_no_winner(self) -> None:
        self.assertIsNone(select_winner((), "min_time"))

    def test_expired_outer_deadline_does_not_call_the_geo_core(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        def boom(*args, **kwargs):
            del args, kwargs
            raise AssertionError("expired envelope called the geo core")

        original = geo_mission._run_pipeline
        geo_mission._run_pipeline = boom
        problem = Problem(
            job_id="job_outer",
            scenario={
                "aerodromes": [{"id": "аэродром 1", "lat": 55.747, "lon": 37.6}],
                "boards": [],
                "required_spectrum": "RGB",
                "criterion": "min_time",
            },
            objective="min_time",
            seed=7,
            time_limit_seconds=90,
        )
        try:
            result = solve(problem, time.monotonic() - 1)
        finally:
            geo_mission._run_pipeline = original
        self.assertIsInstance(result, TimedOut)

    def test_single_call_is_rejected_before_gibrid(self) -> None:
        scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError) as caught:
            solve(
                Problem(
                    job_id="job_meta",
                    scenario=scenario,
                    objective="min_flight_hours",
                    seed=11,
                    time_limit_seconds=90,
                ),
                time.monotonic() + 30,
            )
        self.assertIn("the listener only accepts the geo envelope", str(caught.exception))

    def test_single_takeoff_uav_does_not_use_the_catalog(self) -> None:
        import planes.runtime.enumeration.outer as outer

        scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
        scenario.pop("solver", None)
        self.assertFalse(is_outer_scenario(scenario))
        self.assertIn("takeoff", scenario)
        self.assertIn("uav", scenario)

        def boom_catalog(*args, **kwargs):
            del args, kwargs
            raise AssertionError("single takeoff/uav scenario read the catalog")

        original_catalog = outer.load_catalog
        outer.load_catalog = boom_catalog
        problem = Problem(
            job_id="job_one",
            scenario=scenario,
            objective="min_flight_hours",
            seed=7,
            time_limit_seconds=90,
        )
        try:
            with self.assertRaises(ValueError) as caught:
                solve(problem, time.monotonic() - 1)
        finally:
            outer.load_catalog = original_catalog
        self.assertIn("the listener only accepts the geo envelope", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
