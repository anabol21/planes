"""Outer envelope: one InputData per runnable board card."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import time
import unittest
from pathlib import Path

from planes.runtime.enumeration import candidates, is_outer_scenario, run_candidates
from planes.runtime.logs import log_directory
from planes.runtime.solver import Infeasible, Problem, Solution, solve

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
        scenario["power_coeffs"] = {"kh": 1.0, "kv": 1.0, "kw": 1.0}
        scenario["solver"] = {"turn_time_s": 99.0, "apply_turn_to_base": True}
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
        self.assertEqual(first.power_coeffs.kh, 90)
        self.assertEqual(first.power_coeffs.kv, 0.02)
        self.assertEqual(first.power_coeffs.kw, 0.008)
        self.assertEqual(first.solver.turn_time_s, 5)
        self.assertEqual(first.solver.apply_turn_to_base, False)
        self.assertEqual(first.solver.time_limit_s, 90)
        self.assertNotIn("zone_constraints", first.model_dump())
        self.assertNotIn("obstacles", first.model_dump())
        joined = "\n".join(outcome.disclosures)
        self.assertIn("power_coeffs.kh=90 (estimate)", joined)
        self.assertIn("apply_turn_to_base=false is a fixed core default", joined)

    def test_camera_not_on_the_model_is_rejected(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "riebo-r4", "аэродром 1", 1)]
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
        self.assertIn("riebo-r4", str(caught.exception))
        self.assertEqual(called, [])

    def test_lidar_gemini_pf1b_does_not_call_the_core(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 3)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        scenario = _envelope(profile, "LiDAR", _one_aerodrome(), boards)
        outcome = run_candidates(scenario, seed=7, time_limit_s=30, core=fake)
        self.assertEqual(called, [])
        self.assertEqual(outcome.attempts, ())
        self.assertEqual(outcome.skips, ())
        self.assertEqual(outcome.reason, "no camera covers required spectrum")
        self.assertEqual(len(outcome.mismatches), 1)
        mismatch = outcome.mismatches[0]
        self.assertEqual(mismatch.model_id, "geoscan-gemini")
        self.assertEqual(mismatch.camera_id, "geoscan-pf1b")
        self.assertEqual(mismatch.required_spectrum, "LiDAR")
        self.assertEqual(mismatch.camera_spectra, ("RGB",))

        problem = Problem(
            job_id="job_lidar",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        result = solve(problem, time.monotonic() + 5)
        self.assertIsInstance(result, Infeasible)
        self.assertIn("no camera covers required spectrum", result.limitations)
        self.assertTrue(any("geoscan-gemini" in line and "geoscan-pf1b" in line for line in result.limitations))

        geophysical = run_candidates(
            _envelope(profile, "geophysical", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(geophysical.attempts, ())
        self.assertEqual(geophysical.reason, "no camera covers required spectrum")

        rgb = run_candidates(
            _envelope(profile, "RGB", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(len(called), 1)
        self.assertEqual(rgb.attempts[0].model_id, "geoscan-gemini")
        self.assertEqual(rgb.attempts[0].camera_id, "geoscan-pf1b")
        self.assertEqual(rgb.mismatches, ())

    def test_spectrum_miss_outranks_missing_numbers(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pollux", "аэродром 1", 1)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        outcome = run_candidates(
            _envelope(profile, "LiDAR", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(called, [])
        self.assertEqual(outcome.skips, ())
        self.assertEqual(outcome.reason, "no camera covers required spectrum")
        self.assertEqual(outcome.mismatches[0].camera_spectra, ("multispectral", "RGB"))

    def test_incomplete_pair_does_not_call_the_core(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-201", "sony-zv-e10", "аэродром 1", 1)]
        called: list[object] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data)
            return {"status": "infeasible"}

        outcome = run_candidates(
            _envelope(profile, "RGB", _one_aerodrome(), boards),
            seed=7,
            time_limit_s=30,
            core=fake,
        )
        self.assertEqual(called, [])
        self.assertEqual(outcome.attempts, ())
        self.assertEqual(outcome.reason, "no runnable board")
        self.assertEqual(outcome.mismatches, ())
        self.assertEqual(len(outcome.skips), 1)
        skip = outcome.skips[0]
        self.assertEqual(skip.model_id, "geoscan-201")
        self.assertEqual(skip.camera_id, "sony-zv-e10")
        self.assertIn("focal_length_mm", skip.missing)
        self.assertIn("image_width_px", skip.missing)
        self.assertIn("image_height_px", skip.missing)

        mixed = [
            _board("БВС 1", "geoscan-201", "sony-zv-e10", "аэродром 1", 1),
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
        self.assertEqual(outcome.skips[0].camera_id, "sony-zv-e10")

    def test_default_core_uses_meta_and_keeps_grisha_solver_fields(self) -> None:
        import planes.runtime.enumeration.outer as outer

        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1)]
        scenario = _envelope(_profile(), "RGB", _one_aerodrome(), boards)
        scenario["solver"] = {"turn_time_s": 99.0, "apply_turn_to_base": True}
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
        self.assertEqual(captured["turn_time_s"], 5.0)
        self.assertEqual(captured["apply_turn_to_base"], False)
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


def _optimal(data, solver_choice: str = "auto", *, seed: int = 42):
    del data, solver_choice, seed
    return {
        "status": "optimal",
        "criterion": "min_time",
        "solver": "meta",
        "mission": {
            "mission_time_s": 12.0,
            "total_flight_time_s": 12.0,
            "uav_used": 1,
        },
        "routes": [],
        "strips": [],
        "validation": {},
    }


class CatalogPipelineTest(unittest.TestCase):
    def _solve(self, scenario: dict, job_id: str, core=None):
        import planes.runtime.enumeration.outer as outer

        original = outer._run_optimizer
        if core is not None:
            outer._run_optimizer = lambda: core
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stderr(buffer):
                result = solve(
                    Problem(
                        job_id=job_id,
                        scenario=scenario,
                        objective="min_time",
                        seed=7,
                        time_limit_seconds=30,
                    ),
                    time.monotonic() + 30,
                )
        finally:
            outer._run_optimizer = original
        logged = (log_directory() / f"{job_id}.log").read_text(encoding="utf-8")
        return result, buffer.getvalue(), logged

    def test_rgb_cards_call_the_core_and_name_nonpassport_values(self) -> None:
        profile = _profile()
        boards = [
            _board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1),
            _board("БВС 2", "geoscan-gemini", "sony-umc-r10c-16", "аэродром 1", 1),
            _board("БВС 3", "geoscan-gemini", "sony-umc-r10c-20", "аэродром 1", 1),
            _board("БВС 4", "geoscan-gemini", "geoscan-pollux", "аэродром 1", 1),
            _board("БВС 5", "geoscan-201", "geoscan-pollux", "аэродром 1", 1),
            _board("БВС 6", "geoscan-201", "riebo-r4", "аэродром 1", 1),
            _board("БВС 7", "geoscan-201", "riebo-r6", "аэродром 1", 1),
        ]
        seen: list[tuple[str, str]] = []

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del solver_choice
            self.assertEqual(seed, 7)
            seen.append((data.uav.model, str(data.camera.focal_length_mm)))
            return _optimal(data, seed=seed)

        result, stderr, logged = self._solve(
            _envelope(profile, "RGB", _one_aerodrome(), boards),
            "job_rgb_catalog",
            fake,
        )
        self.assertEqual(
            seen,
            [
                ("Геоскан Gemini", "20.0"),
                ("Геоскан Gemini", "16.0"),
                ("Геоскан Gemini", "20.0"),
                ("Геоскан Gemini", "8.0"),
                ("Геоскан 201", "8.0"),
                ("Геоскан 201", "40.0"),
                ("Геоскан 201", "40.0"),
            ],
        )
        self.assertIsInstance(result, Solution)
        text = "\n".join(result.limitations)
        self.assertIn("power_coeffs.kh=90 (estimate)", text)
        self.assertIn("power_coeffs.kv=0.02 (estimate)", text)
        self.assertIn("power_coeffs.kw=0.008 (estimate)", text)
        self.assertIn("image_width_px=8204 px (calculation)", text)
        self.assertIn("image_height_px=5485 px (calculation)", text)
        self.assertIn("image_width_px=9552 px (calculation)", text)
        self.assertIn("image_height_px=6386 px (calculation)", text)
        self.assertIn("focal_length_mm=16 mm (estimate)", text)
        self.assertIn("focal_length_mm=20 mm (estimate)", text)
        self.assertIn("90 / 0.02 / 0.008", text)
        self.assertIn("220 W (estimate)", text)
        self.assertIn("airspeed_m_s=25 m/s (estimate)", text)
        self.assertIn("climb_m_s=3 m/s (estimate)", text)
        self.assertIn("battery.energy_wh=740 Wh (calculation)", text)
        self.assertIn("apply_turn_to_base=false is a fixed core default", text)
        self.assertIn("turn_time_s=5 s is a fixed core default", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)

    def test_multispectral_pollux_names_calculated_sides(self) -> None:
        profile = _profile()
        boards = [
            _board("БВС 1", "geoscan-gemini", "geoscan-pollux", "аэродром 1", 1),
            _board("БВС 2", "geoscan-201", "geoscan-pollux", "аэродром 1", 1),
        ]
        seen: list[tuple[float, float]] = []

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del solver_choice, seed
            seen.append((data.camera.sensor_width_mm, data.camera.sensor_height_mm))
            return _optimal(data)

        result, stderr, logged = self._solve(
            _envelope(profile, "multispectral", _one_aerodrome(), boards),
            "job_ms_pollux",
            fake,
        )
        self.assertEqual(seen, [(5.04, 3.78), (5.04, 3.78)])
        self.assertIsInstance(result, Solution)
        text = "\n".join(result.limitations)
        self.assertIn("sensor_width_mm=5.04 mm (calculation)", text)
        self.assertIn("sensor_height_mm=3.78 mm (calculation)", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)

    def test_infrared_801_thermal_names_pitch_and_battery(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-801", "geoscan-801-thermal", "аэродром 1", 1)]
        seen: list[tuple[float, float, float, float]] = []

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del solver_choice, seed
            seen.append(
                (
                    data.camera.sensor_width_mm,
                    data.camera.sensor_height_mm,
                    data.uav.battery_wh,
                    data.uav.v_vertical_ms,
                )
            )
            self.assertEqual(data.uav.mass_kg, 1.5)
            self.assertEqual(data.uav.v_air_ms, 15)
            self.assertEqual(data.uav.max_flight_time_s, 2400)
            self.assertEqual(data.uav.max_wind_ms, 10)
            self.assertEqual(data.power_coeffs.kh, 90)
            self.assertEqual(data.solver.turn_time_s, 5)
            self.assertIs(data.solver.apply_turn_to_base, False)
            return _optimal(data)

        result, stderr, logged = self._solve(
            _envelope(profile, "infrared", _one_aerodrome(), boards),
            "job_ir_801",
            fake,
        )
        self.assertEqual(seen, [(10.88, 8.704, 90, 4)])
        self.assertIsInstance(result, Solution)
        text = "\n".join(result.limitations)
        self.assertIn("pixel_pitch_um=17 um (calculation)", text)
        self.assertIn("battery.energy_wh=90 Wh (estimate)", text)
        self.assertIn("climb_m_s=4 m/s (estimate)", text)
        self.assertIn("sensor_width_mm=10.88 mm (calculation)", text)
        self.assertIn("sensor_height_mm=8.704 mm (calculation)", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)

    def test_lidar_on_the_current_catalog_does_not_call_the_core(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-gemini", "geoscan-pf1b", "аэродром 1", 1)]
        called: list[object] = []

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del solver_choice, seed
            called.append(data)
            return _optimal(data)

        result, stderr, logged = self._solve(
            _envelope(profile, "LiDAR", _one_aerodrome(), boards),
            "job_lidar_catalog",
            fake,
        )
        self.assertEqual(called, [])
        self.assertIsInstance(result, Infeasible)
        text = "\n".join(result.limitations)
        self.assertIn("no camera covers required spectrum", text)
        self.assertIn("power_coeffs.kh=90 (estimate)", text)
        self.assertNotIn("apply_turn_to_base=false is a fixed core default", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)

    def test_fixture_lidar_camera_uses_the_same_candidate_path(self) -> None:
        import planes.runtime.enumeration.outer as outer

        catalog = copy.deepcopy(outer.load_catalog())
        catalog["cameras"].append(
            {
                "id": "fixture-lidar",
                "name": "Fixture LiDAR",
                "spectra": ["LiDAR"],
                "sensor_width_mm": {"value": 10, "mark": "passport"},
                "sensor_height_mm": {"value": 8, "mark": "passport"},
                "focal_length_mm": {"value": 12, "mark": "passport"},
                "image_width_px": {"value": 1000, "mark": "passport"},
                "image_height_px": {"value": 800, "mark": "passport"},
                "source": "test fixture",
                "gaps": [],
            }
        )
        catalog["compatibility"].append(
            {
                "uav_model_id": "geoscan-gemini",
                "camera_id": "fixture-lidar",
                "source": "test fixture",
            }
        )
        boards = [_board("БВС 1", "geoscan-gemini", "fixture-lidar", "аэродром 1", 2)]
        called: list[str] = []

        def fake(data, seed: int = 0):
            del seed
            called.append(data.uav.model)
            self.assertEqual(data.camera.focal_length_mm, 12)
            self.assertEqual(data.uav.count, 2)
            return {"status": "infeasible", "reason": "fake lidar"}

        original = outer.load_catalog
        outer.load_catalog = lambda: catalog
        try:
            outcome = run_candidates(
                _envelope(_profile(), "LiDAR", _one_aerodrome(), boards),
                seed=7,
                time_limit_s=30,
                core=fake,
            )
        finally:
            outer.load_catalog = original
        self.assertEqual(called, ["Геоскан Gemini"])
        self.assertEqual(outcome.attempts[0].camera_id, "fixture-lidar")
        self.assertEqual(outcome.mismatches, ())
        self.assertEqual(outcome.skips, ())

    def test_incomplete_optics_name_the_gap_and_still_log(self) -> None:
        profile = _profile()
        boards = [
            _board("БВС 1", "geoscan-201", "sony-zv-e10", "аэродром 1", 1),
            _board("БВС 2", "geoscan-201", "sony-dsc-rx1rm2", "аэродром 1", 1),
            _board("БВС 3", "geoscan-201", "sony-dsc-rx1rm3", "аэродром 1", 1),
            _board("БВС 4", "geoscan-801", "geoscan-801-visible-4-35", "аэродром 1", 1),
            _board("БВС 5", "geoscan-801", "geoscan-801-visible-16", "аэродром 1", 1),
        ]
        called: list[object] = []

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del solver_choice, seed
            called.append(data)
            return _optimal(data)

        result, stderr, logged = self._solve(
            _envelope(profile, "RGB", _one_aerodrome(), boards),
            "job_gaps",
            fake,
        )
        self.assertEqual(called, [])
        self.assertIsInstance(result, Infeasible)
        text = "\n".join(result.limitations)
        self.assertIn("no runnable board", text)
        for camera_id in ("sony-zv-e10", "sony-dsc-rx1rm2", "sony-dsc-rx1rm3"):
            self.assertIn(camera_id, text)
            self.assertIn("focal_length_mm", text)
        self.assertIn("geoscan-801-visible-4-35", text)
        self.assertIn("sensor_width_mm", text)
        self.assertIn("sensor_height_mm", text)
        self.assertIn("image_width_px=4000 px (estimate)", text)
        self.assertIn("battery.energy_wh=740 Wh (calculation)", text)
        self.assertIn("90 / 0.02 / 0.008", text)
        self.assertNotIn("apply_turn_to_base=false is a fixed core default", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)

    def test_infeasible_core_still_names_nonpassport_values(self) -> None:
        profile = _profile()
        boards = [_board("БВС 1", "geoscan-201", "riebo-r4", "аэродром 1", 1)]

        def fake(data, solver_choice: str = "auto", *, seed: int = 42):
            del data, solver_choice, seed
            return {"status": "infeasible", "reason": "fake infeasible"}

        result, stderr, logged = self._solve(
            _envelope(profile, "RGB", _one_aerodrome(), boards),
            "job_infeasible_201",
            fake,
        )
        self.assertIsInstance(result, Infeasible)
        text = "\n".join(result.limitations)
        self.assertIn("fake infeasible", text)
        self.assertIn("image_width_px=8204 px (calculation)", text)
        self.assertIn("220 W (estimate)", text)
        self.assertIn("apply_turn_to_base=false is a fixed core default", text)
        self.assertIn(text, stderr)
        self.assertIn(text, logged)


if __name__ == "__main__":
    unittest.main()
