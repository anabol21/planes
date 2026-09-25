"""The live path returns one winning call. These cases use a fake core."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from planes.runtime.enumeration import Attempt, EnumerationResult
from planes.runtime.solver import Infeasible, Problem, Solution, TimedOut, solve

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

_ASSEMBLED = ("routes", "strips", "validation", "mission")


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
    pad_id: str,
    type_id: str,
    mission_time: float,
    flight_time: float,
    status: str = "optimal",
    criterion: str = "min_time",
) -> Attempt:
    return Attempt(
        pad_id=pad_id,
        type_id=type_id,
        data=None,
        result=_plan(mission_time, flight_time, status, criterion),
    )


class WinnerSelectionTest(unittest.TestCase):
    def _solve(self, attempts: list[Attempt], criterion: str, *, stopped: bool = False):
        import planes.runtime.solver as solver_module

        def fake_run(scenario, *, seed, time_limit_s, core=None, deadline=None):
            del scenario, seed, time_limit_s, core, deadline
            return EnumerationResult(attempts=tuple(attempts), stopped_for_deadline=stopped)

        original = solver_module.run_candidates
        solver_module.run_candidates = fake_run
        problem = Problem(
            job_id="job_outer",
            scenario={"pads": [], "uav_types": [], "criterion": criterion},
            objective="min_time" if criterion == "min_time" else "min_total_flight_time",
            seed=7,
            time_limit_seconds=90,
        )
        try:
            return solve(problem, time.monotonic() + 30)
        finally:
            solver_module.run_candidates = original

    def test_min_time_keeps_the_shorter_mission_and_names_the_winner(self) -> None:
        slow = _attempt("p-slow", "t-slow", 20.0, 5.0)
        fast = _attempt("p-fast", "t-fast", 9.0, 30.0)
        result = self._solve([slow, fast], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.objective_value, 9.0)
        self.assertEqual(result.mission_plan["mission"]["mission_time_s"], 9.0)
        self.assertIn("winning pad id: p-fast", result.limitations)
        self.assertIn("winning type id: t-fast", result.limitations)
        for key in _ASSEMBLED:
            self.assertIn(key, result.mission_plan)

    def test_min_flight_hours_reads_total_flight_time(self) -> None:
        slow = _attempt("p-slow", "t-slow", 20.0, 5.0, criterion="min_flight_hours")
        fast = _attempt("p-fast", "t-fast", 9.0, 30.0, criterion="min_flight_hours")
        result = self._solve([slow, fast], "min_flight_hours")
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.objective_value, 5.0)
        self.assertIn("winning pad id: p-slow", result.limitations)
        self.assertIn("winning type id: t-slow", result.limitations)

    def test_tie_keeps_the_earlier_call(self) -> None:
        first = _attempt("p1", "t1", 9.0, 9.0)
        second = _attempt("p2", "t2", 9.0, 9.0)
        result = self._solve([first, second], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertIn("winning pad id: p1", result.limitations)

    def test_heuristic_limitation_stays_with_the_winner(self) -> None:
        attempt = _attempt("p1", "t1", 4.0, 4.0, status="heuristic")
        result = self._solve([attempt], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertTrue(any("not globally optimal" in item for item in result.limitations))
        self.assertIn("winning pad id: p1", result.limitations)

    def test_no_compatible_pair_is_infeasible(self) -> None:
        result = self._solve([], "min_time")
        self.assertIsInstance(result, Infeasible)
        self.assertIn("no compatible pad and type", result.limitations)

    def test_deadline_without_a_success_is_timed_out(self) -> None:
        result = self._solve([], "min_time", stopped=True)
        self.assertIsInstance(result, TimedOut)

    def test_single_uav_scenario_does_not_enumerate(self) -> None:
        import planes.runtime.solver as solver_module

        scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
        scenario.pop("solver", None)

        def boom(*args, **kwargs):
            del args, kwargs
            raise AssertionError("single-uav scenario enumerated")

        original = solver_module.run_candidates
        solver_module.run_candidates = boom
        problem = Problem(
            job_id="job_one",
            scenario=scenario,
            objective="min_flight_hours",
            seed=7,
            time_limit_seconds=90,
        )
        try:
            result = solve(problem, time.monotonic() - 1)
        finally:
            solver_module.run_candidates = original
        self.assertIsInstance(result, TimedOut)


if __name__ == "__main__":
    unittest.main()
