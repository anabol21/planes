"""Executable shared contract regressions."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from planes.contracts import parse_optimization_v0, parse_scenario_v0

GOLDEN = REPO / "tests" / "fixtures" / "scenario_v0_full.json"


class ScenarioV0ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_golden_round_trip_is_exact(self) -> None:
        scenario = parse_scenario_v0(self.request["scenario"])
        optimization = parse_optimization_v0(self.request["optimization"])
        self.assertEqual(self.request["scenario"], scenario.to_dict())
        self.assertEqual(self.request["optimization"], optimization.to_dict())

    def test_unknown_field_fails_instead_of_being_dropped(self) -> None:
        scenario = copy.deepcopy(self.request["scenario"])
        scenario["hidden_default"] = True
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            parse_scenario_v0(scenario)

    def test_invalid_geometry_and_units_fail(self) -> None:
        scenario = copy.deepcopy(self.request["scenario"])
        scenario["survey_areas"][0]["geometry"]["coordinates"][0].pop()
        with self.assertRaisesRegex(ValueError, "must be closed"):
            parse_scenario_v0(scenario)

        scenario = copy.deepcopy(self.request["scenario"])
        scenario["wind"]["speed_mps"] = -1
        with self.assertRaisesRegex(ValueError, "speed_mps"):
            parse_scenario_v0(scenario)


if __name__ == "__main__":
    unittest.main()
