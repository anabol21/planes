"""One real core run on the small Moscow rectangle. Not a 4x4 sweep."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from planes.runtime.enumeration import run_candidates

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

_AREA = [
    [37.601, 55.7480],
    [37.609, 55.7480],
    [37.609, 55.7525],
    [37.601, 55.7525],
]


def _scenario() -> dict:
    raw = json.loads(_INPUT.read_text(encoding="utf-8"))
    flight = dict(raw["uav"])
    flight.pop("count", None)
    return {
        "area": _AREA,
        "criterion": "min_time",
        "wind": raw["wind"],
        "gsd_cm_per_px": raw["gsd_cm_per_px"],
        "survey": raw["survey"],
        "power_coeffs": raw["power_coeffs"],
        "required_camera": "Sony UMC-R10C",
        "required_spectrum": "RGB",
        "uav_types": [
            {
                "id": "gemini-rgb",
                "camera": {"name": "Sony UMC-R10C", **raw["camera"]},
                "spectra": ["RGB"],
                **flight,
            }
        ],
        "pads": [
            {
                "id": "moscow-sw",
                "lat": raw["takeoff"]["lat"],
                "lon": raw["takeoff"]["lon"],
                "types": [{"id": "gemini-rgb", "count": 1}],
            }
        ],
    }


class MoscowCoreTest(unittest.TestCase):
    def test_one_uav_records_mission_consumption(self) -> None:
        outcome = run_candidates(_scenario(), seed=7, time_limit_s=90)
        self.assertEqual(len(outcome.attempts), 1)
        self.assertFalse(outcome.stopped_for_deadline)
        attempt = outcome.attempts[0]
        self.assertEqual(attempt.pad_id, "moscow-sw")
        self.assertEqual(attempt.type_id, "gemini-rgb")
        self.assertEqual(attempt.data.uav.count, 1)
        self.assertEqual(attempt.data.solver.time_limit_s, 90)
        result = attempt.result
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["solver"], "milp")
        mission = result["mission"]
        routes = result["routes"]
        self.assertEqual(len(routes), 1)
        energy = routes[0]["energy_breakdown_wh"]
        # Recorded from this one run (seed 7, time_limit_s 90, one UAV).
        self.assertEqual(mission["uav_used"], 1)
        self.assertAlmostEqual(mission["mission_time_s"], 907.4262445369322, places=5)
        self.assertAlmostEqual(mission["total_flight_time_s"], 846.1496487922514, places=5)
        self.assertAlmostEqual(energy["takeoff"], 1.5319148936170213, places=5)
        self.assertAlmostEqual(energy["transit"], 24.85439970382018, places=5)
        self.assertAlmostEqual(energy["turns"], 2.687, places=5)
        self.assertAlmostEqual(energy["survey"], 22.98313599184159, places=5)
        self.assertAlmostEqual(energy["landing"], 1.5319148936170213, places=5)
        self.assertAlmostEqual(energy["total"], 53.58836548289582, places=5)


if __name__ == "__main__":
    unittest.main()
