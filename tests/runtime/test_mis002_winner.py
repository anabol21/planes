"""The live path returns one winning call. These cases use a fake core."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from planes.runtime.enumeration import Attempt, EnumerationResult, is_outer_scenario
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
    model_id: str,
    camera_id: str,
    mission_time: float,
    flight_time: float,
    status: str = "optimal",
    criterion: str = "min_time",
) -> Attempt:
    return Attempt(
        pad_id=pad_id,
        model_id=model_id,
        camera_id=camera_id,
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
            scenario={"pads": [], "required_spectrum": "RGB", "criterion": criterion},
            objective="min_time" if criterion == "min_time" else "min_total_flight_time",
            seed=7,
            time_limit_seconds=90,
        )
        try:
            return solve(problem, time.monotonic() + 30)
        finally:
            solver_module.run_candidates = original

    def test_min_time_keeps_the_shorter_mission_and_names_the_winner(self) -> None:
        slow = _attempt("p-slow", "m-slow", "c-slow", 20.0, 5.0)
        fast = _attempt("p-fast", "m-fast", "c-fast", 9.0, 30.0)
        result = self._solve([slow, fast], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.objective_value, 9.0)
        self.assertEqual(result.mission_plan["mission"]["mission_time_s"], 9.0)
        self.assertIn("winning pad id: p-fast", result.limitations)
        self.assertIn("winning model id: m-fast", result.limitations)
        self.assertIn("winning camera id: c-fast", result.limitations)
        for key in _ASSEMBLED:
            self.assertIn(key, result.mission_plan)

    def test_min_flight_hours_reads_total_flight_time(self) -> None:
        slow = _attempt("p-slow", "m-slow", "c-slow", 20.0, 5.0, criterion="min_flight_hours")
        fast = _attempt("p-fast", "m-fast", "c-fast", 9.0, 30.0, criterion="min_flight_hours")
        result = self._solve([slow, fast], "min_flight_hours")
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.objective_value, 5.0)
        self.assertIn("winning pad id: p-slow", result.limitations)
        self.assertIn("winning model id: m-slow", result.limitations)
        self.assertIn("winning camera id: c-slow", result.limitations)

    def test_tie_keeps_the_earlier_call(self) -> None:
        first = _attempt("p1", "m1", "c1", 9.0, 9.0)
        second = _attempt("p2", "m2", "c2", 9.0, 9.0)
        result = self._solve([first, second], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertIn("winning pad id: p1", result.limitations)
        self.assertIn("winning model id: m1", result.limitations)

    def test_heuristic_limitation_stays_with_the_winner(self) -> None:
        attempt = _attempt("p1", "m1", "c1", 4.0, 4.0, status="heuristic")
        result = self._solve([attempt], "min_time")
        self.assertIsInstance(result, Solution)
        self.assertTrue(any("not globally optimal" in item for item in result.limitations))
        self.assertIn("winning pad id: p1", result.limitations)
        self.assertIn("winning model id: m1", result.limitations)
        self.assertIn("winning camera id: c1", result.limitations)

    def test_no_runnable_pair_is_infeasible(self) -> None:
        result = self._solve([], "min_time")
        self.assertIsInstance(result, Infeasible)
        self.assertIn("no runnable uav and camera for spectrum", result.limitations)

    def test_deadline_without_a_success_is_timed_out(self) -> None:
        result = self._solve([], "min_time", stopped=True)
        self.assertIsInstance(result, TimedOut)

    def test_single_call_uses_meta_and_keeps_grisha_solver_fields(self) -> None:
        import planes.runtime.solver as solver_module

        scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
        shipped = scenario["solver"]
        captured: dict[str, object] = {}

        def spy(data, solver_choice: str = "auto", *, seed: int = 42):
            captured["choice"] = solver_choice
            captured["seed"] = seed
            captured["turn_time_s"] = data.solver.turn_time_s
            captured["apply_turn_to_base"] = data.solver.apply_turn_to_base
            captured["time_limit_s"] = data.solver.time_limit_s
            return {"status": "infeasible", "reason": "spy"}

        solve(
            Problem(
                job_id="job_warm",
                scenario=scenario,
                objective="min_flight_hours",
                seed=7,
                time_limit_seconds=90,
            ),
            time.monotonic() - 1,
        )
        cached = solver_module._optimizer
        self.assertIsNotNone(cached)
        solver_module._optimizer = (spy, cached[1], cached[2])
        try:
            result = solve(
                Problem(
                    job_id="job_meta",
                    scenario=scenario,
                    objective="min_flight_hours",
                    seed=11,
                    time_limit_seconds=90,
                ),
                time.monotonic() + 30,
            )
        finally:
            solver_module._optimizer = cached
        self.assertIsInstance(result, Infeasible)
        self.assertEqual(captured["choice"], "meta")
        self.assertEqual(captured["seed"], 11)
        self.assertEqual(captured["turn_time_s"], shipped["turn_time_s"])
        self.assertEqual(captured["apply_turn_to_base"], shipped["apply_turn_to_base"])
        self.assertEqual(captured["time_limit_s"], 90)

    def test_single_takeoff_uav_does_not_use_the_catalog(self) -> None:
        import planes.runtime.enumeration.outer as outer
        import planes.runtime.solver as solver_module

        scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
        scenario.pop("solver", None)
        self.assertFalse(is_outer_scenario(scenario))
        self.assertIn("takeoff", scenario)
        self.assertIn("uav", scenario)

        def boom(*args, **kwargs):
            del args, kwargs
            raise AssertionError("single takeoff/uav scenario enumerated")

        def boom_catalog(*args, **kwargs):
            del args, kwargs
            raise AssertionError("single takeoff/uav scenario read the catalog")

        original = solver_module.run_candidates
        original_catalog = outer.load_catalog
        solver_module.run_candidates = boom
        outer.load_catalog = boom_catalog
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
            outer.load_catalog = original_catalog
        self.assertIsInstance(result, TimedOut)


if __name__ == "__main__":
    unittest.main()
