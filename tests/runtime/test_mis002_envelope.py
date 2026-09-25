"""Outer envelope: filter (pad, type) pairs and build one InputData per call."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from planes.runtime.enumeration import candidates, run_candidates

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


def _profile() -> dict:
    raw = json.loads(_INPUT.read_text(encoding="utf-8"))
    return {
        "gsd_cm_per_px": raw["gsd_cm_per_px"],
        "survey": raw["survey"],
        "power_coeffs": raw["power_coeffs"],
        "wind": raw["wind"],
        "optics": raw["camera"],
        "flight": {
            "model": raw["uav"]["model"],
            "mass_kg": raw["uav"]["mass_kg"],
            "max_flight_time_s": raw["uav"]["max_flight_time_s"],
            "battery_wh": raw["uav"]["battery_wh"],
            "v_air_ms": raw["uav"]["v_air_ms"],
            "v_vertical_ms": raw["uav"]["v_vertical_ms"],
            "max_wind_ms": raw["uav"]["max_wind_ms"],
        },
    }


def _type(type_id: str, camera_name: str, spectra: list[str], profile: dict) -> dict:
    return {
        "id": type_id,
        "camera": {"name": camera_name, **profile["optics"]},
        "spectra": spectra,
        **profile["flight"],
        "model": type_id,
    }


def _pad(pad_id: str, lat: float, lon: float, stock: list[tuple[str, int]]) -> dict:
    return {
        "id": pad_id,
        "lat": lat,
        "lon": lon,
        "types": [{"id": type_id, "count": count} for type_id, count in stock],
    }


def _envelope(profile: dict, types: list[dict], pads: list[dict]) -> dict:
    return {
        "area": [[37.601, 55.748], [37.609, 55.748], [37.609, 55.7525], [37.601, 55.7525]],
        "criterion": "min_time",
        "wind": profile["wind"],
        "gsd_cm_per_px": profile["gsd_cm_per_px"],
        "survey": profile["survey"],
        "power_coeffs": profile["power_coeffs"],
        "required_camera": "cam-a",
        "required_spectrum": "vis",
        "uav_types": types,
        "pads": pads,
        "zone_constraints": {"kml_path": "zone.kml"},
        "terrain": {"kml_path": "terrain.kml"},
    }


class EnvelopeFilterTest(unittest.TestCase):
    def test_four_by_four_drops_incompatible_pairs_in_pad_order(self) -> None:
        profile = _profile()
        types = [
            _type("t1", "cam-a", ["vis", "nir"], profile),
            _type("t2", "cam-a", ["nir"], profile),
            _type("t3", "cam-b", ["vis"], profile),
            _type("t4", "cam-a", ["vis"], profile),
        ]
        pads = [
            _pad("p1", 55.747, 37.600, [("t1", 2), ("t2", 1), ("t3", 1)]),
            _pad("p2", 55.748, 37.601, [("t4", 1), ("t1", 3)]),
            _pad("p3", 55.749, 37.602, [("t3", 1)]),
            _pad("p4", 55.750, 37.603, [("t4", 2), ("t2", 1)]),
        ]
        scenario = _envelope(profile, types, pads)
        self.assertEqual(len(scenario["pads"]), 4)
        self.assertEqual(len(scenario["uav_types"]), 4)

        first = candidates(scenario, time_limit_s=90)
        second = candidates(scenario, time_limit_s=90)
        order = [(item.pad_id, item.type_id, item.data.uav.count) for item in first]
        self.assertEqual(
            [(item.pad_id, item.type_id, item.data.uav.count) for item in second],
            order,
        )
        self.assertEqual(
            order,
            [("p1", "t1", 2), ("p2", "t4", 1), ("p2", "t1", 3), ("p4", "t4", 2)],
        )
        self.assertLessEqual(len(order), 16)
        dropped = {pair for pair in order if pair[1] in {"t2", "t3"}}
        self.assertEqual(dropped, set())

        seen: list[tuple[str, str]] = []

        def fake(data, seed: int = 0):
            self.assertEqual(seed, 7)
            self.assertEqual(data.takeoff.__class__.__name__, "Takeoff")
            self.assertEqual(data.uav.__class__.__name__, "UAV")
            self.assertNotIsInstance(data.takeoff, list)
            self.assertNotIsInstance(data.uav, list)
            seen.append((data.takeoff.lat, data.takeoff.lon, data.uav.model, data.uav.count))
            return {"status": "infeasible", "reason": "fake"}

        outcome = run_candidates(scenario, seed=7, time_limit_s=90, core=fake)
        self.assertEqual(len(outcome.attempts), len(order))
        self.assertLessEqual(len(outcome.attempts), 16)
        self.assertFalse(outcome.stopped_for_deadline)
        self.assertEqual(
            seen,
            [
                (55.747, 37.600, "t1", 2),
                (55.748, 37.601, "t4", 1),
                (55.748, 37.601, "t1", 3),
                (55.750, 37.603, "t4", 2),
            ],
        )
        for attempt in outcome.attempts:
            self.assertEqual(attempt.data.camera.focal_length_mm, profile["optics"]["focal_length_mm"])
            self.assertFalse(hasattr(attempt.data, "pads"))

    def test_full_square_is_sixteen_calls_and_a_fifth_type_is_rejected(self) -> None:
        profile = _profile()
        types = [_type(f"t{index}", "cam-a", ["vis"], profile) for index in range(1, 5)]
        stock = [(item["id"], 1) for item in types]
        pads = [_pad(f"p{index}", 55.74 + index / 1000, 37.60, stock) for index in range(1, 5)]
        scenario = _envelope(profile, types, pads)
        calls: list[tuple[str, str]] = []

        def fake(data, seed: int = 0):
            del data, seed
            return {"status": "infeasible"}

        outcome = run_candidates(scenario, seed=7, time_limit_s=30, core=fake)
        calls = [(item.pad_id, item.type_id) for item in outcome.attempts]
        self.assertEqual(len(calls), 16)
        self.assertEqual(calls, [(f"p{pad}", f"t{vehicle}") for pad in range(1, 5) for vehicle in range(1, 5)])

        extra = _type("t5", "cam-a", ["vis"], profile)
        with self.assertRaises(ValueError) as caught:
            candidates(_envelope(profile, [*types, extra], pads[:1]))
        self.assertIn("at most 4", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
