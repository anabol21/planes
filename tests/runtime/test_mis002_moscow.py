"""Catalog enumeration on the small Moscow rectangle. The core is a fake."""

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


def _scenario(spectrum: str, pads: list[dict]) -> dict:
    raw = json.loads(_INPUT.read_text(encoding="utf-8"))
    return {
        "area": _AREA,
        "criterion": "min_time",
        "wind": raw["wind"],
        "gsd_cm_per_px": raw["gsd_cm_per_px"],
        "survey": raw["survey"],
        "power_coeffs": raw["power_coeffs"],
        "required_spectrum": spectrum,
        "pads": pads,
    }


class MoscowCatalogTest(unittest.TestCase):
    def test_two_pads_stay_on_gemini_pf1b_without_a_real_core_sweep(self) -> None:
        pads = [
            {"id": "moscow-sw", "lat": 55.7470, "lon": 37.6000, "count": 1},
            {"id": "moscow-ne", "lat": 55.7520, "lon": 37.6080, "count": 3},
        ]
        seen: list[tuple[str, str, int]] = []

        def fake(data, seed: int = 0):
            self.assertEqual(seed, 7)
            seen.append((data.takeoff.lat, data.uav.model, data.uav.count))
            return {"status": "infeasible", "reason": "fake"}

        outcome = run_candidates(_scenario("RGB", pads), seed=7, time_limit_s=90, core=fake)
        self.assertEqual(
            [(item.pad_id, item.model_id, item.camera_id) for item in outcome.attempts],
            [
                ("moscow-sw", "geoscan-gemini", "geoscan-pf1b"),
                ("moscow-ne", "geoscan-gemini", "geoscan-pf1b"),
            ],
        )
        self.assertEqual(seen, [(55.7470, "Геоскан Gemini", 1), (55.7520, "Геоскан Gemini", 3)])
        self.assertEqual(outcome.attempts[0].data.uav.v_air_ms, 15)
        self.assertEqual(outcome.attempts[1].data.camera.sensor_width_mm, 23.5)


if __name__ == "__main__":
    unittest.main()
