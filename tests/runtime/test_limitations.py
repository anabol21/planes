"""Identical limitation strings are kept once, in first-seen order."""

from __future__ import annotations

import json
import unittest

from planes.runtime.physical_check import annotate_result
from planes.runtime.solver import Infeasible, Solution
from planes.runtime.types import make_response, parse_response, unique_limitations


_REASON = (
    "uncovered swaths=5378: a swath exceeds endurance even with recharge and best pads"
)
_COUNT = "uncovered_swaths=5378"
_PER_UAV = "БВС 1: one swath exceeds endurance even with best pads"
_PHYS = "PHYS-ENDURANCE: Вылет длиннее выносливости борта"


class UniqueLimitationsTest(unittest.TestCase):
    def test_endurance_spam_keeps_distinct_lines(self) -> None:
        lines = (
            _REASON,
            _COUNT,
            _REASON,
            _REASON,
            *([_PER_UAV] * 20),
            "allow_recharge=True",
        )
        self.assertEqual(
            unique_limitations(lines),
            (_REASON, _COUNT, _PER_UAV, "allow_recharge=True"),
        )

    def test_empty_and_already_unique_are_unchanged(self) -> None:
        self.assertEqual(unique_limitations(()), ())
        self.assertEqual(unique_limitations((_REASON, _COUNT)), (_REASON, _COUNT))

    def test_make_response_and_parse_response_dedupe(self) -> None:
        spam = [_REASON, _COUNT, _REASON, *([_PER_UAV] * 5), _PHYS]
        response = make_response(
            job_id="job-limit-001",
            outcome="infeasible",
            method="runtime-test",
            objective="min_time",
            runtime_seconds=0.1,
            seed=7,
            limitations=spam,
        )
        self.assertEqual(
            response.solver_report.limitations,
            (_REASON, _COUNT, _PER_UAV, _PHYS),
        )
        parsed = parse_response(
            {
                "contract_version": "v0",
                "job_id": "job-limit-001",
                "outcome": "infeasible",
                "solver_report": {
                    "method": "grisha_mvp_fields2cover_isolated",
                    "objective": "min_time",
                    "runtime_seconds": 1.0,
                    "seed": 7,
                    "limitations": spam,
                },
                "artifacts": [],
            }
        )
        self.assertEqual(
            parsed.solver_report.limitations,
            (_REASON, _COUNT, _PER_UAV, _PHYS),
        )

    def test_annotate_result_does_not_reintroduce_duplicates(self) -> None:
        result = annotate_result(
            Infeasible((_REASON, _REASON, _PER_UAV, _PER_UAV)),
            {},
        )
        self.assertEqual(result.limitations.count(_REASON), 1)
        self.assertEqual(result.limitations.count(_PER_UAV), 1)
        self.assertEqual(len(set(result.limitations)), len(result.limitations))

    def test_pipeline_judge_emits_unique_lines(self) -> None:
        from planes.runtime.pipeline import judge
        from planes.runtime.solver import Problem

        problem = Problem(
            job_id="job-limit-002",
            scenario={"id": "scenario_01"},
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        judged = judge(
            problem,
            Solution(
                mission_plan={"kind": "injected"},
                method="injected",
                objective_value=1.0,
                limitations=(_REASON, _COUNT, _REASON, _PER_UAV, _PER_UAV),
            ),
            0.2,
        )
        self.assertEqual(
            judged.solver_report.limitations,
            (_REASON, _COUNT, _PER_UAV),
        )
        payload = json.loads(
            json.dumps(
                {
                    "limitations": list(judged.solver_report.limitations),
                }
            )
        )
        self.assertEqual(payload["limitations"], [_REASON, _COUNT, _PER_UAV])
