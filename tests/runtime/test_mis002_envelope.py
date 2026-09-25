"""Outer envelope: catalog pairs on user pads, one InputData per runnable triple."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from planes.runtime.enumeration import candidates, is_outer_scenario, run_candidates
from planes.runtime.solver import Problem, solve

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
    }


def _pad(pad_id: str, lat: float, lon: float, count: int) -> dict:
    return {"id": pad_id, "lat": lat, "lon": lon, "count": count}


def _envelope(profile: dict, spectrum: str, pads: list[dict]) -> dict:
    return {
        "area": [[37.601, 55.748], [37.609, 55.748], [37.609, 55.7525], [37.601, 55.7525]],
        "criterion": "min_time",
        "wind": profile["wind"],
        "gsd_cm_per_px": profile["gsd_cm_per_px"],
        "survey": profile["survey"],
        "power_coeffs": profile["power_coeffs"],
        "required_spectrum": spectrum,
        "pads": pads,
    }


def _complete_model(model_id: str) -> dict:
    return {
        "id": model_id,
        "name": model_id,
        "mass_kg": 2,
        "airspeed_m_s": 15,
        "climb_m_s": 5,
        "max_wind_m_s": 10,
        "flight_time_s": 2400,
        "battery": {"energy_wh": 100},
    }


def _complete_camera(camera_id: str) -> dict:
    return {
        "id": camera_id,
        "spectra": ["RGB"],
        "sensor_width_mm": 23.5,
        "sensor_height_mm": 15.6,
        "focal_length_mm": 20,
        "image_width_px": 6000,
        "image_height_px": 4000,
    }


class EnvelopeFilterTest(unittest.TestCase):
    def test_rgb_two_pads_calls_gemini_pf1b_in_pad_order(self) -> None:
        profile = _profile()
        pads = [
            _pad("pad-a", 55.747, 37.600, 2),
            _pad("pad-b", 55.750, 37.610, 1),
        ]
        scenario = _envelope(profile, "RGB", pads)
        seen: list[tuple[str, str]] = []

        def fake(data, seed: int = 0):
            self.assertEqual(seed, 7)
            self.assertEqual(data.takeoff.__class__.__name__, "Takeoff")
            self.assertEqual(data.uav.__class__.__name__, "UAV")
            seen.append((data.uav.model, data.camera.focal_length_mm))
            return {"status": "infeasible", "reason": "fake"}

        outcome = run_candidates(scenario, seed=7, time_limit_s=90, core=fake)
        self.assertEqual(
            [(item.pad_id, item.model_id, item.camera_id, item.data.uav.count) for item in outcome.attempts],
            [
                ("pad-a", "geoscan-gemini", "geoscan-pf1b", 2),
                ("pad-b", "geoscan-gemini", "geoscan-pf1b", 1),
            ],
        )
        self.assertEqual(len(seen), 2)
        self.assertFalse(outcome.stopped_for_deadline)
        first = outcome.attempts[0].data
        second = outcome.attempts[1].data
        self.assertIsNot(first, second)
        self.assertEqual(first.uav.model, "Геоскан Gemini")
        self.assertEqual(first.uav.v_air_ms, 15)
        self.assertEqual(first.uav.battery_wh, 144.7)
        self.assertEqual(first.uav.mass_kg, 2)
        self.assertEqual(first.uav.max_flight_time_s, 2400)
        self.assertEqual(first.uav.v_vertical_ms, 5)
        self.assertEqual(first.uav.max_wind_ms, 10)
        self.assertEqual(first.camera.sensor_width_mm, 23.5)
        self.assertEqual(first.camera.sensor_height_mm, 15.6)
        self.assertEqual(first.camera.focal_length_mm, 20)
        self.assertEqual(first.camera.image_width_px, 6000)
        self.assertEqual(first.camera.image_height_px, 4000)
        self.assertEqual(first.takeoff.lat, 55.747)
        self.assertEqual(first.takeoff.lon, 37.600)
        self.assertEqual(second.takeoff.lat, 55.750)
        self.assertEqual(second.uav.count, 1)
        shipped = json.loads(_INPUT.read_text(encoding="utf-8"))["solver"]
        self.assertEqual(first.solver.turn_time_s, shipped["turn_time_s"])
        self.assertEqual(first.solver.apply_turn_to_base, shipped["apply_turn_to_base"])
        self.assertEqual(first.solver.time_limit_s, 90)
        called = {(item.model_id, item.camera_id) for item in outcome.attempts}
        self.assertEqual(called, {("geoscan-gemini", "geoscan-pf1b")})
        skipped_cameras = {skip.camera_id for skip in outcome.skips}
        self.assertIn("geoscan-pollux", skipped_cameras)
        self.assertIn("sony-umc-r10c", skipped_cameras)

    def test_four_pads_and_one_rgb_pair_make_four_calls(self) -> None:
        profile = _profile()
        pads = [_pad(f"p{index}", 55.74 + index / 1000, 37.60, 1) for index in range(1, 5)]
        calls: list[str] = []

        def fake(data, seed: int = 0):
            del data, seed
            return {"status": "infeasible"}

        outcome = run_candidates(_envelope(profile, "RGB", pads), seed=7, time_limit_s=30, core=fake)
        calls = [item.pad_id for item in outcome.attempts]
        self.assertEqual(calls, ["p1", "p2", "p3", "p4"])
        self.assertEqual({(item.model_id, item.camera_id) for item in outcome.attempts}, {("geoscan-gemini", "geoscan-pf1b")})

    def test_multispectral_does_not_call_the_core_and_names_the_pollux_skip(self) -> None:
        profile = _profile()
        pads = [_pad("pad-a", 55.747, 37.6, 1)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        outcome = run_candidates(_envelope(profile, "multispectral", pads), seed=7, time_limit_s=30, core=fake)
        self.assertEqual(called, [])
        self.assertEqual(outcome.attempts, ())
        self.assertEqual(outcome.reason, "no runnable uav and camera for spectrum")
        pollux = [skip for skip in outcome.skips if skip.camera_id == "geoscan-pollux"]
        self.assertGreaterEqual(len(pollux), 1)
        gemini = pollux[0]
        self.assertEqual(gemini.model_id, "geoscan-gemini")
        self.assertEqual(gemini.camera_id, "geoscan-pollux")
        self.assertIn("sensor_width_mm", gemini.missing)
        self.assertIn("sensor_height_mm", gemini.missing)

    def test_default_core_uses_meta_and_keeps_grisha_solver_fields(self) -> None:
        import planes.runtime.enumeration.outer as outer

        shipped = json.loads(_INPUT.read_text(encoding="utf-8"))["solver"]
        scenario = _envelope(_profile(), "RGB", [_pad("pad-a", 55.747, 37.6, 1)])
        scenario["solver"] = shipped
        captured: dict[str, object] = {}

        def spy(data, solver_choice: str = "auto", *, seed: int = 42):
            captured["choice"] = solver_choice
            captured["seed"] = seed
            captured["turn_time_s"] = data.solver.turn_time_s
            captured["apply_turn_to_base"] = data.solver.apply_turn_to_base
            captured["time_limit_s"] = data.solver.time_limit_s
            return {"status": "infeasible", "reason": "spy"}

        original = outer._run_optimizer
        outer._run_optimizer = lambda: spy
        try:
            outcome = run_candidates(scenario, seed=7, time_limit_s=90)
        finally:
            outer._run_optimizer = original
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(captured["choice"], "meta")
        self.assertEqual(captured["seed"], 7)
        self.assertEqual(captured["turn_time_s"], shipped["turn_time_s"])
        self.assertEqual(captured["apply_turn_to_base"], shipped["apply_turn_to_base"])
        self.assertEqual(captured["time_limit_s"], 90)

    def test_uav_types_envelope_is_rejected(self) -> None:
        profile = _profile()
        scenario = _envelope(profile, "RGB", [_pad("pad-a", 55.747, 37.6, 1)])
        scenario["uav_types"] = [{"id": "legacy"}]
        self.assertFalse(is_outer_scenario(scenario))
        with self.assertRaises(ValueError) as caught:
            candidates(scenario)
        self.assertIn("uav_types", str(caught.exception))
        problem = Problem(
            job_id="job_legacy",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        with self.assertRaises(ValueError) as solved:
            solve(problem, time.monotonic() + 5)
        self.assertIn("uav_types", str(solved.exception))

    def test_more_than_sixteen_runnable_triples_is_an_error(self) -> None:
        models = [_complete_model(f"m{index}") for index in range(1, 6)]
        cameras = [_complete_camera(f"c{index}") for index in range(1, 6)]
        catalog = {
            "uav_models": models,
            "cameras": cameras,
            "compatibility": [
                {"uav_model_id": f"m{index}", "camera_id": f"c{index}"}
                for index in range(1, 6)
            ],
        }
        pads = [_pad(f"p{index}", 55.74, 37.60, 1) for index in range(1, 5)]
        scenario = _envelope(_profile(), "RGB", pads)
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        with patch("planes.runtime.enumeration.outer.load_catalog", return_value=catalog):
            with self.assertRaises(ValueError) as caught:
                run_candidates(scenario, seed=7, time_limit_s=30, core=fake)
        self.assertIn("16", str(caught.exception))
        self.assertEqual(called, [])

        catalog["compatibility"] = catalog["compatibility"][:4]
        catalog["uav_models"] = models[:4]
        catalog["cameras"] = cameras[:4]
        with patch("planes.runtime.enumeration.outer.load_catalog", return_value=catalog):
            outcome = run_candidates(scenario, seed=7, time_limit_s=30, core=fake)
        self.assertEqual(len(outcome.attempts), 16)


if __name__ == "__main__":
    unittest.main()
