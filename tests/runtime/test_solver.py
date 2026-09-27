"""The listener accepts only the geo envelope.

A one-card scenario raises ``ValueError`` before any gibrid import.
``_map_result`` remains for assembled result dicts. The gibrid package
itself is probed only by ``test_run_accepts_seed_without_files``.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unittest
from pathlib import Path

from support import load_fixture

from planes.runtime.pipeline import run as run_pipeline
from planes.runtime.solver import Problem, solve

_GEO_ONLY = "the listener only accepts the geo envelope"

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
    def _assert_rejected_before_gibrid(self, scenario: dict, **overrides: object) -> str:
        import planes.runtime.solver as solver_module

        before = {
            name
            for name in sys.modules
            if name == "optimizer" or name.startswith("optimizer.")
        }
        with self.assertRaises(ValueError) as caught:
            solve(_problem(scenario, **overrides), time.monotonic() + 30)
        message = str(caught.exception)
        self.assertIn(_GEO_ONLY, message)
        self.assertNotIn("infeasible", message.lower())
        after = {
            name
            for name in sys.modules
            if name == "optimizer" or name.startswith("optimizer.")
        }
        self.assertEqual(after, before)
        self.assertFalse(hasattr(solver_module, "_optimizer"))
        source = Path(solver_module.__file__).read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"\b(run_optimizer|solve_milp|solve_metaheuristic)\s*\(", source)
        )
        self.assertIsNone(re.search(r"""["']meta["']""", source))
        self.assertNotIn(str(_GIBRID), sys.path)
        return message

    def test_one_card_is_rejected_before_gibrid(self) -> None:
        self._assert_rejected_before_gibrid(_grisha_scenario(), time_limit_seconds=2)

    def test_one_card_with_more_uavs_is_rejected(self) -> None:
        scenario = _grisha_scenario()
        scenario["uav"] = {**scenario["uav"], "count": 4}
        self._assert_rejected_before_gibrid(scenario, seed=7)

    def test_foreign_scenario_is_error_not_infeasible(self) -> None:
        message = self._assert_rejected_before_gibrid(_FOREIGN_SCENARIO, objective="min_time")
        self.assertIn(_GEO_ONLY, message)

        request = load_fixture()
        request["scenario"] = _FOREIGN_SCENARIO
        request["job_id"] = "job_foreign"
        response = run_pipeline(json.dumps(request).encode("utf-8"))
        self.assertEqual(response.outcome, "error")
        self.assertNotEqual(response.outcome, "infeasible")
        self.assertIsNone(response.mission_plan)
        self.assertIn(_GEO_ONLY, response.solver_report.limitations)

    def test_expired_deadline_still_rejects_one_card(self) -> None:
        import planes.runtime.solver as solver_module

        before = {
            name
            for name in sys.modules
            if name == "optimizer" or name.startswith("optimizer.")
        }
        with self.assertRaises(ValueError) as caught:
            solve(_problem(_grisha_scenario()), time.monotonic() - 1)
        self.assertIn(_GEO_ONLY, str(caught.exception))
        after = {
            name
            for name in sys.modules
            if name == "optimizer" or name.startswith("optimizer.")
        }
        self.assertEqual(after, before)
        self.assertFalse(hasattr(solver_module, "_optimizer"))

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
