"""Scenario v0 reaches the legacy adapter complete and narrows explicitly."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from planes.runtime.legacy_scenario import to_legacy_envelope

GOLDEN = REPO / "tests" / "fixtures" / "scenario_v0_full.json"


class LegacyScenarioAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = json.loads(GOLDEN.read_text(encoding="utf-8"))["scenario"]

    def test_maps_single_area_without_hiding_transport_fields(self) -> None:
        self.scenario["survey_areas"] = self.scenario["survey_areas"][:1]
        legacy = to_legacy_envelope(self.scenario, "min_total_flight_time")
        self.assertEqual("min_flight_hours", legacy["criterion"])
        self.assertEqual(self.scenario["survey_areas"][0]["geometry"]["coordinates"][0], legacy["area"])
        self.assertEqual(2, len(legacy["aerodromes"]))
        self.assertEqual(2, len(legacy["boards"]))
        self.assertEqual(1, len(legacy["zone_constraints"]))
        self.assertEqual(2, len(legacy["obstacles"]))
        self.assertEqual(6.5, legacy["wind"]["speed_ms"])
        self.assertEqual(4.5, legacy["gsd_cm_per_px"])

    def test_rejects_multiple_areas_instead_of_dropping_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one survey area"):
            to_legacy_envelope(self.scenario, "min_time")


if __name__ == "__main__":
    unittest.main()
