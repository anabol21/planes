"""Adapter from Grisha's in-memory optimizer to Solution, Infeasible, and TimedOut."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

from support import load_fixture

from planes.runtime.pipeline import run as run_pipeline
from planes.runtime.solver import Infeasible, Problem, Solution, TimedOut, solve

_GIBRID = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "basic_model"
    / "gibrid-optimizer"
)
_INPUT = _GIBRID / "data" / "input.json"

_FOREIGN_SCENARIO = {
    "scenario_id": "demo-01",
    "crs": "EPSG:4326",
    "scenario_profile": "team_assumption_multi_uav_kml_v0",
    "semantic_validation_performed": False,
    "uavs": [
        {
            "uav_id": "uav-01",
            "model": "Geoscan Gemini",
            "payload_model": "Sony UMC-R10C",
            "cruise_speed_m_s": 15,
            "battery_capacity_wh": 144.7,
            "max_flight_time_s": 2400,
            "launch_point": {"crs": "EPSG:4326", "lon_deg": 30.31, "lat_deg": 59.94},
            "landing_point": {"crs": "EPSG:4326", "lon_deg": 30.31, "lat_deg": 59.94},
        }
    ],
    "survey": {"survey_type": "RGB", "task_geometry": None},
    "restricted_zones": [],
    "obstacles": [],
    "wind": {"speed_m_s": 5.0, "direction_from_deg": 270.0},
    "prototype_limitations": [
        "KML is structurally summarized in the browser; geometry and flight safety are not validated.",
    ],
}


def _grisha_scenario(**overrides: object) -> dict:
    scenario = json.loads(_INPUT.read_text(encoding="utf-8"))
    scenario.pop("solver", None)
    scenario.update(overrides)
    return scenario


def _problem(scenario: dict, **overrides: object) -> Problem:
    values = {
        "job_id": "job_solver",
        "scenario": scenario,
        "objective": "min_flight_hours",
        "seed": 7,
        "time_limit_seconds": 60,
    }
    values.update(overrides)
    return Problem(**values)


class SolverAdapterTest(unittest.TestCase):
    def test_feasible_plan_uses_assembled_dict(self) -> None:
        result = solve(
            _problem(_grisha_scenario(), time_limit_seconds=2),
            time.monotonic() + 30,
        )
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.method, "meta")
        self.assertEqual(result.mission_plan["status"], "heuristic")
        self.assertEqual(result.mission_plan["solver"], "meta")
        for key in ("routes", "strips", "validation", "mission"):
            self.assertIn(key, result.mission_plan)
        self.assertNotIn("routes_raw", result.mission_plan)
        self.assertIsInstance(result.objective_value, float)
        self.assertTrue(any("not globally optimal" in item for item in result.limitations))
        self.assertNotIn(str(_GIBRID), sys.path)

    def test_heuristic_is_not_globally_optimal(self) -> None:
        scenario = _grisha_scenario()
        scenario["uav"] = {**scenario["uav"], "count": 4}
        result = solve(_problem(scenario, seed=7), time.monotonic() + 60)
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.mission_plan["status"], "heuristic")
        self.assertEqual(result.method, "meta")
        self.assertTrue(
            any("not globally optimal" in item for item in result.limitations)
        )

    def test_solver_infeasible(self) -> None:
        import planes.runtime.solver as solver_module

        solve(_problem(_grisha_scenario()), time.monotonic() - 1)
        cached = solver_module._optimizer
        self.assertIsNotNone(cached)

        def infeasible(data, solver_choice: str = "meta", *, seed: int = 42):
            del data, solver_choice, seed
            return {"status": "infeasible", "reason": "wind"}

        solver_module._optimizer = (infeasible, cached[1], cached[2])
        try:
            result = solve(_problem(_grisha_scenario()), time.monotonic() + 30)
        finally:
            solver_module._optimizer = cached
        self.assertIsInstance(result, Infeasible)
        self.assertNotIsInstance(result, Solution)
        self.assertIn("wind", result.limitations)

    def test_foreign_scenario_is_error_not_infeasible(self) -> None:
        problem = _problem(_FOREIGN_SCENARIO, objective="min_time")
        with self.assertRaises(ValueError) as caught:
            solve(problem, time.monotonic() + 30)
        message = str(caught.exception)
        self.assertIn("missing fields:", message)
        for name in ("takeoff", "uav", "area", "gsd_cm_per_px", "criterion", "camera", "power_coeffs"):
            self.assertIn(name, message)
        self.assertNotIn("infeasible", message)

        request = load_fixture()
        request["scenario"] = _FOREIGN_SCENARIO
        request["job_id"] = "job_foreign"
        response = run_pipeline(json.dumps(request).encode("utf-8"))
        self.assertEqual(response.outcome, "error")
        self.assertNotEqual(response.outcome, "infeasible")
        self.assertIsNone(response.mission_plan)

    def test_solver_stop_without_solution_is_timed_out(self) -> None:
        import planes.runtime.solver as solver_module

        solve(_problem(_grisha_scenario()), time.monotonic() - 1)
        cached = solver_module._optimizer
        self.assertIsNotNone(cached)

        def stopped(data, solver_choice: str = "meta", *, seed: int = 42):
            del data, solver_choice, seed
            return {"status": "unknown", "reason": "Решатель не вернул решение"}

        solver_module._optimizer = (stopped, cached[1], cached[2])
        try:
            result = solve(_problem(_grisha_scenario()), time.monotonic() + 30)
        finally:
            solver_module._optimizer = cached
        self.assertIsInstance(result, TimedOut)
        self.assertTrue(any("time limit" in item for item in result.limitations))

    def test_expired_deadline_is_timed_out(self) -> None:
        result = solve(_problem(_grisha_scenario()), time.monotonic() - 1)
        self.assertIsInstance(result, TimedOut)
        self.assertTrue(any("time limit" in item for item in result.limitations))

    def test_run_accepts_seed_without_files(self) -> None:
        root = str(_GIBRID)
        inserted = root not in sys.path
        if inserted:
            sys.path.insert(0, root)
        try:
            import optimizer.main as optimizer_main
            from optimizer.models import InputData

            captured: dict[str, int] = {}

            def fake_meta(data, pre, seed: int = 42, pop_size: int = 40, generations: int = 150):
                del data, pre, pop_size, generations
                captured["seed"] = seed
                return {"status": "infeasible", "reason": "seed-probe"}

            original = optimizer_main.solve_metaheuristic
            optimizer_main.solve_metaheuristic = fake_meta
            try:
                data = InputData(**json.loads(_INPUT.read_text(encoding="utf-8")))
                out = optimizer_main.run(data, "meta", seed=11)
            finally:
                optimizer_main.solve_metaheuristic = original
        finally:
            if inserted and root in sys.path:
                sys.path.remove(root)
        self.assertEqual(captured["seed"], 11)
        self.assertEqual(out["status"], "infeasible")
        self.assertIn("strip_count", out)


if __name__ == "__main__":
    unittest.main()
