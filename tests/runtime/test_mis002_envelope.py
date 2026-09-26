"""Outer envelope: one InputData per runnable board card."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

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


def _aerodrome(aerodrome_id: str, lat: float, lon: float) -> dict:
    return {"id": aerodrome_id, "lat": lat, "lon": lon}


def _board(board_id: str, model_id: str, camera_id: str, aerodrome_id: str, count: int) -> dict:
    return {
        "id": board_id,
        "model_id": model_id,
        "camera_id": camera_id,
        "aerodrome_id": aerodrome_id,
        "count": count,
    }


def _envelope(profile: dict, spectrum: str, aerodromes: list[dict], boards: list[dict]) -> dict:
    return {
        "area": [[37.601, 55.748], [37.609, 55.748], [37.609, 55.7525], [37.601, 55.7525]],
        "criterion": "min_time",
        "wind": profile["wind"],
        "gsd_cm_per_px": profile["gsd_cm_per_px"],
        "survey": profile["survey"],
        "power_coeffs": profile["power_coeffs"],
        "required_spectrum": spectrum,
        "aerodromes": aerodromes,
        "boards": boards,
    }


def _one_aerodrome() -> list[dict]:
    return [_aerodrome("аэродром 1", 55.747, 37.6)]


class EnvelopeFilterTest(unittest.TestCase):
    def test_two_boards_call_the_core_in_card_order(self) -> None:
        profile = _profile()
        aerodromes = [
            _aerodrome("аэродром 1", 55.747, 37.600),
            _aerodrome("аэродром 2", 55.750, 37.610),
        ]
        boards = [
            _board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 2),
            _board("БВС 2", "geoscan-gemini", "geoscan-pf1b", "аэродром 2", 1),
        ]
        scenario = _envelope(profile, "RGB", aerodromes, boards)
        self.assertTrue(is_outer_scenario(scenario))
        seen: list[tuple[str, float]] = []

        def fake(data, seed: int = 0):
            self.assertEqual(seed, 7)
            self.assertEqual(data.takeoff.__class__.__name__, "Takeoff")
            self.assertEqual(data.uav.__class__.__name__, "UAV")
            seen.append((data.uav.model, data.camera.focal_length_mm))
            return {"status": "infeasible", "reason": "fake"}

        outcome = run_candidates(scenario, seed=7, time_limit_s=90, core=fake)
        self.assertEqual(
            [
                (item.board_id, item.aerodrome_id, item.model_id, item.camera_id, item.data.uav.count)
                for item in outcome.attempts
            ],
            [
                ("БВС 1", "аэродром 1", "geoscan-gemini", "geoscan-pf1b", 2),
                ("БВС 2", "аэродром 2", "geoscan-gemini", "geoscan-pf1b", 1),
            ],
        )
        self.assertEqual(len(seen), 2)
        self.assertEqual(outcome.skips, ())
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
        self.assertEqual(second.takeoff.lon, 37.610)
        self.assertEqual(second.uav.count, 1)
        shipped = json.loads(_INPUT.read_text(encoding="utf-8"))["solver"]
        self.assertEqual(first.solver.turn_time_s, shipped["turn_time_s"])
        self.assertEqual(first.solver.apply_turn_to_base, shipped["apply_turn_to_base"])
        self.assertEqual(first.solver.time_limit_s, 90)

    def test_camera_not_on_the_model_is_rejected(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "sony-a6000", "аэродром 1", 1)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        with self.assertRaises(ValueError) as caught:
            run_candidates(
                _envelope(profile, "RGB", _one_aerodrome(), boards),
                seed=7,
                time_limit_s=30,
                core=fake,
            )
        self.assertIn("not compatible", str(caught.exception))
        self.assertIn("sony-a6000", str(caught.exception))
        self.assertEqual(called, [])

    def test_multispectral_does_not_hide_the_model_rgb_camera(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 3)]
        called: list[str] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data.uav.model)
            return {"status": "infeasible"}

        outcome = run_candidates(
            _envelope(profile, "multispectral", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(called, ["Геоскан Gemini"])
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(outcome.attempts[0].model_id, "geoscan-gemini")
        self.assertEqual(outcome.attempts[0].camera_id, "geoscan-pf1b")
        self.assertEqual(outcome.attempts[0].data.uav.count, 3)
        self.assertEqual(outcome.skips, ())

    def test_incomplete_pair_does_not_call_the_core(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pollux", "аэродром 1", 1)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        outcome = run_candidates(
            _envelope(profile, "multispectral", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(called, [])
        self.assertEqual(outcome.attempts, ())
        self.assertEqual(outcome.reason, "no runnable board")
        self.assertEqual(len(outcome.skips), 1)
        skip = outcome.skips[0]
        self.assertEqual(skip.model_id, "geoscan-gemini")
        self.assertEqual(skip.camera_id, "geoscan-pollux")
        self.assertIn("sensor_width_mm", skip.missing)
        self.assertIn("sensor_height_mm", skip.missing)

        mixed = [
            _board("БВС 1", "geoscan-gemini", "geoscan-pollux", "аэродром 1", 1),
            _board("БВС 2", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 4),
        ]
        outcome = run_candidates(
            _envelope(profile, "RGB", _one_aerodrome(), mixed),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(len(called), 1)
        self.assertEqual(
            [(item.board_id, item.camera_id, item.data.uav.count) for item in outcome.attempts],
            [("БВС 2", "geoscan-pf1b", 4)],
        )
        self.assertEqual(outcome.skips[0].camera_id, "geoscan-pollux")

    def test_default_core_uses_meta_and_keeps_grisha_solver_fields(self) -> None:
        import planes.runtime.enumeration.outer as outer

        shipped = json.loads(_INPUT.read_text(encoding="utf-8"))["solver"]
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1)]
        scenario = _envelope(_profile(), "RGB", _one_aerodrome(), boards)
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
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1)]
        scenario = _envelope(profile, "RGB", _one_aerodrome(), boards)
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

    def test_pads_envelope_is_not_accepted(self) -> None:
        profile = _profile()
        scenario = {
            "area": [[37.601, 55.748], [37.609, 55.748], [37.609, 55.7525], [37.601, 55.7525]],
            "criterion": "min_time",
            "wind": profile["wind"],
            "gsd_cm_per_px": profile["gsd_cm_per_px"],
            "survey": profile["survey"],
            "power_coeffs": profile["power_coeffs"],
            "required_spectrum": "RGB",
            "pads": [{"id": "pad-01", "lat": 55.747, "lon": 37.6, "count": 1}],
        }
        self.assertFalse(is_outer_scenario(scenario))
        with self.assertRaises(ValueError) as caught:
            candidates(scenario)
        self.assertIn("pads", str(caught.exception))
        problem = Problem(
            job_id="job_pads",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        with self.assertRaises(ValueError) as solved:
            solve(problem, time.monotonic() + 5)
        self.assertIn("pads", str(solved.exception))

    def test_more_than_sixteen_runnable_cards_is_an_error(self) -> None:
        profile = _profile()
        aerodromes = _one_aerodrome()

        def boards(count: int) -> list[dict]:
            return [
                _board(f"БВС {index}", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1)
                for index in range(1, count + 1)
            ]

        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        with self.assertRaises(ValueError) as caught:
            run_candidates(
                _envelope(profile, "RGB", aerodromes, boards(17)),
                seed=7,
                time_limit_s=30,
                core=fake,
            )
        self.assertIn("16", str(caught.exception))
        self.assertEqual(called, [])

        outcome = run_candidates(
            _envelope(profile, "RGB", aerodromes, boards(16)),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(len(outcome.attempts), 16)
        self.assertEqual(outcome.attempts[0].board_id, "БВС 1")
        self.assertEqual(outcome.attempts[15].board_id, "БВС 16")


if __name__ == "__main__":
    unittest.main()
