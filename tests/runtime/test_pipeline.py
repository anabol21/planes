"""Pipeline stages with an injected solve, plus the empty default body."""

from __future__ import annotations

import json
import time
import unittest

from support import load_fixture

from planes.runtime.pipeline import bind, compile, run
from planes.runtime.solver import Infeasible, Solution, TimedOut
from planes.runtime.types import parse_request, response_to_dict


class PipelineTest(unittest.TestCase):
    def test_injected_solve_is_feasible(self) -> None:
        seen: dict[str, object] = {}

        def solve(problem, deadline: float):
            seen["scenario"] = problem.scenario
            seen["job_id"] = problem.job_id
            seen["deadline"] = deadline
            return Solution(
                mission_plan={"kind": "injected", "job_id": problem.job_id},
                method="injected",
                objective_value=1.5,
                limitations=("injected plan",),
            )

        started = time.monotonic()
        response = run(json.dumps(load_fixture()).encode("utf-8"), solve)
        self.assertEqual(response.outcome, "feasible")
        self.assertEqual(response.mission_plan, {"kind": "injected", "job_id": "job_01"})
        self.assertEqual(response.solver_report.method, "injected")
        self.assertEqual(seen["scenario"], {"id": "scenario_01"})
        self.assertEqual(seen["job_id"], "job_01")
        self.assertGreater(seen["deadline"], started)

    def test_injected_solve_is_infeasible_without_plan(self) -> None:
        response = run(
            json.dumps(load_fixture()).encode("utf-8"),
            lambda _problem, _deadline: Infeasible(("no route",)),
        )
        self.assertEqual(response.outcome, "infeasible")
        self.assertIsNone(response.mission_plan)
        self.assertNotIn("mission_plan", response_to_dict(response))
        self.assertIn("no route", response.solver_report.limitations)

    def test_injected_solve_is_timed_out(self) -> None:
        response = run(
            json.dumps(load_fixture()).encode("utf-8"),
            lambda _problem, _deadline: TimedOut(("deadline reached",)),
        )
        self.assertEqual(response.outcome, "timed_out")
        self.assertIsNone(response.mission_plan)
        self.assertNotIn("mission_plan", response_to_dict(response))

    def test_default_solve_is_not_implemented(self) -> None:
        response = run(json.dumps(load_fixture()).encode("utf-8"))
        self.assertEqual(response.outcome, "error")
        self.assertIsNone(response.mission_plan)
        self.assertIn("solver body is not implemented", response.solver_report.limitations)

    def test_bad_json_is_error_not_infeasible(self) -> None:
        response = run(b"not-json")
        self.assertEqual(response.outcome, "error")
        self.assertNotEqual(response.outcome, "infeasible")

    def test_compile_keeps_the_scenario_object(self) -> None:
        scenario = {"id": "scenario_01", "note": "opaque"}
        request = parse_request({**load_fixture(), "scenario": scenario})
        problem = compile(bind(request))
        self.assertEqual(problem.scenario, scenario)
        self.assertEqual(problem.objective, "min_time")
        self.assertEqual(problem.seed, 7)
        self.assertEqual(problem.time_limit_seconds, 30)


if __name__ == "__main__":
    unittest.main()
