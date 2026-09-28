"""CAT-001B: real catalogs, strict physics, provenance, wind and real-core smoke."""

from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/planes/model/itog_model/mvp_optimizator"
sys.path.insert(0, str(CORE / "src"))

from planner.io.catalog import Catalog, get_default_catalog
from planner.io.dem import FlatDEM
from planner.models import UAVConfig
from planner.physics.factory import (build_physics_params, build_physics_model,
                                     validate_wind_capability)
from planner.solver import pipeline as core_pipeline
from planner.solver.counters import Counters
from planes.integration.kml.constraints import parse_survey_polygon
from planes.runtime import geo_mission
from planes.runtime.solver import Problem, Solution
from tests.runtime.test_stitch_audit_seams import _board, _scenario, _SURVEY
from tests.runtime.test_geo_kml_stitch import _geotiff_bytes


EXPECTED = {
    # mass, working/survey speed, climb, descent, seconds, Wh, reserve, wind
    "gemini": (2, 12, 12, 5, 5, 2400, 144.7, 0.05, 10),
    "geoscan201": (8.5, 25, 25, 3, 2, 10800, 740, 0.05, 12),
    "geoscan801": (1.5, 12, 12, 4, 0.5, 2400, 126.28, 0.05, 10),
}
PARAMS = ("mass_kg", "v_air_mps", "v_survey_mps", "v_climb_mps", "v_descent_mps",
          "T_max_s", "E_batt_wh", "reserve_fraction", "max_wind_m_s")
SMOKES = (
    ("geoscan-gemini", "geoscan-pf1b", "RGB", "gemini", "pf1b"),
    ("geoscan-201", "riebo-r6", "RGB", "geoscan201", "riebo-r6"),
    ("geoscan-801", "geoscan-801-thermal", "infrared", "geoscan801", "801-thermal"),
)
SMALL_SURVEY = """<kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.6000,55.7500 37.6010,55.7500 37.6010,55.7506 37.6000,55.7506 37.6000,55.7500
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"""


def uav(model):
    return UAVConfig(id="test-uav", model=model, camera_id="pf1b", vpp_id="test-vpp")


def mission_for(scenario):
    return geo_mission._mission(scenario, survey_polygons=parse_survey_polygon(_SURVEY),
                               constraints=[], dem_path=Path("test-only-flat.tif"), dem=FlatDEM())


class LiveUavPhysicsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = get_default_catalog()
        geo_mission._core_symbols()  # populate cache before any injected catalog
        cls.fleet = json.loads((ROOT / "src/planes/runtime/catalog/fleet_catalog.json").read_text(encoding="utf-8"))

    def test_all_selectable_models_map_to_strict_configuration(self):
        self.assertEqual({m["id"] for m in self.fleet["uav_models"]}, set(geo_mission._MODEL_IDS))
        for external, internal in geo_mission._MODEL_IDS.items():
            with self.subTest(model=external):
                self.assertEqual(geo_mission._translate_model(external, self.catalog), internal)
                pp = build_physics_params(uav(internal), self.catalog)
                self.assertEqual(tuple(getattr(pp, f) for f in PARAMS), EXPECTED[internal])
                self.assertGreater(pp.mass_kg, 0)
                self.assertLess(pp.reserve_fraction, 1)
                self.assertGreaterEqual(pp.reserve_fraction, 0)
                for f in PARAMS:
                    self.assertTrue(math.isfinite(getattr(pp, f)))

    def test_every_required_field_missing_rejects_every_aircraft(self):
        for model in EXPECTED:
            block = self.catalog.get_aircraft(model)["physics"]
            fields = [key for key, value in block.items() if isinstance(value, dict)]
            for key in fields + ["battery_id", "power_model", "mass_semantics", "takeoff_mode", "landing_mode", "schema_version"]:
                with self.subTest(model=model, missing=key):
                    data = copy.deepcopy(self.catalog._data)
                    del data["aircraft"][model]["physics"][key]
                    with self.assertRaises(ValueError):
                        build_physics_params(uav(model), Catalog(data))
            data = copy.deepcopy(self.catalog._data)
            del data["aircraft"][model]["physics"]
            with self.assertRaisesRegex(ValueError, "normalized physics"):
                build_physics_params(uav(model), Catalog(data))

    def test_invalid_values_units_marks_and_sources_are_rejected(self):
        for model in EXPECTED:
            for field, changes in (
                ("mass_kg", [{"value": x} for x in (None, True, "2 kg", 0, -1, math.nan, math.inf)]),
                ("reserve_fraction", [{"value": x} for x in (-0.01, 1, 2, math.nan)]),
                ("max_wind_m_s", [{"value": -1}]),
                ("battery_energy_wh", [{"unit": "Ah"}, {"mark": "unmarked"}, {"source": ""}, {"note": ""}]),
            ):
                for change in changes:
                    with self.subTest(model=model, field=field, change=change):
                        data = copy.deepcopy(self.catalog._data)
                        data["aircraft"][model]["physics"][field].update(change)
                        with self.assertRaises(ValueError):
                            build_physics_params(uav(model), Catalog(data))

    def test_normalized_values_win_over_text_and_mvp_no_generic_parser(self):
        for model in EXPECTED:
            data = copy.deepcopy(self.catalog._data)
            data["aircraft"][model]["specs"] = {}
            data["mvp_estimates"] = {}
            with patch("planner.physics.factory._legacy_physics_params", side_effect=AssertionError("generic physics used")):
                pp = build_physics_params(uav(model), Catalog(data))
            self.assertEqual(tuple(getattr(pp, f) for f in PARAMS), EXPECTED[model])

    def test_battery_id_resolution_and_no_cross_aircraft_battery(self):
        for model in EXPECTED:
            config = self.catalog.get_aircraft(model)["physics"]
            explicit = uav(model).model_copy(update={"battery_id": config["battery_id"]})
            self.assertEqual(build_physics_params(explicit, self.catalog).E_batt_wh, EXPECTED[model][6])
            wrong = uav(model).model_copy(update={"battery_id": "battery-201" if model != "geoscan201" else "battery-gemini"})
            with self.assertRaisesRegex(ValueError, "unsupported battery"):
                build_physics_params(wrong, self.catalog)
            data = copy.deepcopy(self.catalog._data)
            del data["batteries"][config["battery_id"]]
            with self.assertRaisesRegex(ValueError, "missing battery"):
                build_physics_params(uav(model), Catalog(data))

    def test_explicit_legacy_opt_in_only(self):
        data = copy.deepcopy(self.catalog._data)
        del data["aircraft"]["gemini"]["physics"]
        legacy = Catalog(data)
        with self.assertRaises(ValueError):
            build_physics_params(uav("gemini"), legacy)
        self.assertEqual(build_physics_params(uav("gemini"), legacy, strict=False).E_batt_wh, 144.7)

    def test_individual_catalog_reserve_not_mission_default(self):
        data = copy.deepcopy(self.catalog._data)
        data["aircraft"]["geoscan801"]["physics"]["reserve_fraction"]["value"] = 0.12
        self.assertEqual(build_physics_params(uav("geoscan801"), Catalog(data)).reserve_fraction, 0.12)
        with self.assertRaisesRegex(ValueError, "reserve override"):
            build_physics_params(uav("geoscan801"), Catalog(data), reserve_fraction=0.05)

    def test_201_mtow_not_mass_plus_payload_and_power(self):
        pp = build_physics_params(uav("geoscan201"), self.catalog)
        self.assertEqual(pp.mass_kg, 8.5)
        self.assertNotEqual(pp.mass_kg, 8.5 + 1.5)
        self.assertEqual(build_physics_model(pp).power_w(25, 0), 220)
        self.assertEqual((pp.k_h, pp.k_v, pp.k_w), (0, 0, 0))
        self.assertEqual(pp.v_min_mps, pp.v_stall_mps)
        self.assertAlmostEqual(pp.t_turn_s, math.pi * 110 / 25, places=3)

    def test_conflicting_explicit_mission_reserve_fails_not_silently_ignored(self):
        mission, _ = mission_for(_scenario())
        mission.params.reserve_fraction = 0.25
        with self.assertRaisesRegex(ValueError, "mission reserve override"):
            core_pipeline._generate_all_swaths(mission, 0)

    def test_launch_landing_and_energy_use_independent_rates(self):
        for model in EXPECTED:
            pp = build_physics_params(uav(model), self.catalog)
            pp.v_vert_mps = 999  # historical scalar must not drive either phase
            flight = build_physics_model(pp)
            self.assertAlmostEqual(flight.takeoff_time_s(120), pp.T_catapult_s + 120 / pp.v_climb_mps)
            self.assertAlmostEqual(flight.landing_time_s(120), pp.T_parachute_s + 120 / pp.v_descent_mps)
            if model == "geoscan201":
                self.assertEqual((flight.takeoff_energy_wh(120), flight.landing_energy_wh(120)), (0, 0))
            else:
                self.assertAlmostEqual(flight.landing_energy_wh(120), pp.k_h * pp.mass_kg * flight.landing_time_s(120) / 3600)

    def test_801_energy_source_and_mismatch_resolution(self):
        pp = build_physics_params(uav("geoscan801"), self.catalog)
        self.assertAlmostEqual(pp.E_batt_wh, 15.4 * 8.2)
        power = build_physics_model(pp).power_w(pp.v_survey_mps, 0)
        self.assertAlmostEqual(power, 169.56)
        self.assertAlmostEqual(pp.E_batt_wh / (pp.T_max_s / 3600), 189.42)
        self.assertAlmostEqual(pp.E_batt_wh * (1-pp.reserve_fraction) / power * 60, 42.45081387119603)
        self.assertLess(90 * 0.95 / power * 60, 31)

    def test_waypoint_transition_uses_descent_not_climb_scalar(self):
        class Identity:
            def transform(self, x, y):
                return x, y

        points = []
        core_pipeline._append_transition(points, [(0, 0), (100, 0)], 100, 0,
                                         Identity(), v_climb_mps=3, v_ground_mps=10,
                                         v_descent_mps=2)
        self.assertEqual(points[0].alt_m, 80)  # 10 s moving descent at 2, not 3 m/s
        self.assertEqual(points[-1].alt_m, 0)  # existing endpoint completion retained

    def test_swath_geometry_receives_distinct_catalog_rates(self):
        for external, camera, spectrum, internal, _ in SMOKES:
            s = _scenario()
            s["boards"] = [_board("rates", external, camera)]
            s["required_spectrum"] = spectrum
            mission, _ = mission_for(s)
            with patch.object(core_pipeline, "generate_swaths_for_area", return_value=([], 120)) as generated:
                core_pipeline._generate_all_swaths(mission, 0)
            self.assertEqual(generated.call_args.kwargs["v_climb_mps"], EXPECTED[internal][3])
            self.assertEqual(generated.call_args.kwargs["v_descent_mps"], EXPECTED[internal][4])

    def test_energy_sanity_all_models(self):
        # Loose diagnostic bound: max endurance and survey are different regimes;
        # outside factor 2 requires a catalog investigation, not coefficient fitting.
        for model in EXPECTED:
            pp = build_physics_params(uav(model), self.catalog)
            implied = pp.E_batt_wh / (pp.T_max_s / 3600)
            nominal = build_physics_model(pp).power_w(pp.v_survey_mps, 0)
            self.assertGreater(nominal / implied, 0.5)
            self.assertLess(nominal / implied, 2)
            self.assertGreater(pp.E_batt_wh * (1-pp.reserve_fraction), 0)

    def test_runtime_duplicates_are_numeric_consistent_with_semantics(self):
        for runtime in self.fleet["uav_models"]:
            internal = geo_mission._MODEL_IDS[runtime["id"]]
            p = self.catalog.get_aircraft(internal)["physics"]
            for key in ("mass_kg", "climb_m_s", "descent_m_s", "survey_speed_m_s", "max_wind_m_s",
                        "flight_time_s", "reserve_fraction", "takeoff_overhead_s", "landing_overhead_s", "recharge_time_s"):
                self.assertEqual(runtime[key]["value"], p[key]["value"], (internal, key))
            self.assertEqual(runtime["mass_semantics"], p["mass_semantics"])
            self.assertEqual(runtime["battery"]["energy_wh"], p["battery_energy_wh"])
            self.assertEqual(runtime["live_turn_time_s"], p["turn_time_s"])
            key = "airspeed_m_s" if internal == "geoscan201" else "airspeed_estimate_m_s"
            self.assertEqual(runtime[key]["value"], p["airspeed_m_s"]["value"])
            if internal != "geoscan201":
                self.assertEqual(runtime["airspeed_m_s"]["value"], p["max_horizontal_speed_m_s"]["value"])
                for coeff in ("kh", "kv", "kw"):
                    self.assertEqual(runtime["power_coeffs"][coeff]["value"], p[coeff]["value"])
            else:
                self.assertEqual(runtime["power_const_w"]["value"], p["constant_power_w"]["value"])
            battery = self.catalog.get_battery(p["battery_id"])["specs"]["power"]
            raw_energy = battery.get("energy_wh", battery.get("energy"))
            self.assertEqual(float(str(raw_energy).removesuffix(" Wh")), p["battery_energy_wh"]["value"])

    def test_wind_below_equal_above_and_invalid_all_models(self):
        for model in EXPECTED:
            pp = build_physics_params(uav(model), self.catalog)
            for speed in (0, pp.max_wind_m_s - 0.01, pp.max_wind_m_s):
                validate_wind_capability(pp, speed)
            for speed in (pp.max_wind_m_s + 0.01, math.nan, math.inf, -1, True):
                with self.assertRaises(ValueError):
                    validate_wind_capability(pp, speed)

    def test_representative_boards_below_above_wind(self):
        for external, camera, spectrum, internal, _ in SMOKES:
            s = _scenario()
            s["boards"] = [_board("wind-board", external, camera)]
            s["required_spectrum"] = spectrum
            s["wind"]["speed_ms"] = EXPECTED[internal][-1] - 0.01
            mission, notes = mission_for(s)
            self.assertEqual(mission.uavs[0].model, internal)
            self.assertTrue(any(f"aircraft {internal} reserve_fraction" in n for n in notes))
            s["wind"]["speed_ms"] = EXPECTED[internal][-1] + 0.01
            with self.assertRaisesRegex(ValueError, "wind-board.*exceeds max_wind"):
                mission_for(s)

    def test_second_board_wind_limit_rejects_whole_mission(self):
        s = _scenario()
        s["boards"] = [_board("201", "geoscan-201", "riebo-r6"),
                       _board("Gemini", "geoscan-gemini", "geoscan-pf1b")]
        s["wind"]["speed_ms"] = 11
        with self.assertRaisesRegex(ValueError, "Gemini.*mission rejected"):
            mission_for(s)

    def test_shared_physics_first_uav_limitation_is_disclosed(self):
        s = _scenario()
        s["boards"] = [_board("gemini", "geoscan-gemini", "geoscan-pollux"),
                       _board("201", "geoscan-201", "geoscan-pollux")]
        mission, notes = mission_for(s)
        self.assertTrue(any("shared swath physics uses the first" in n for n in notes))
        with patch.object(core_pipeline, "generate_swaths_for_area", return_value=([], 120)) as generated:
            core_pipeline._generate_all_swaths(mission, 0)
            self.assertEqual(generated.call_args.kwargs["mass_kg"], 2)
            reversed_mission = mission.model_copy(update={"uavs": list(reversed(mission.uavs))})
            core_pipeline._generate_all_swaths(reversed_mission, 0)
            self.assertEqual(generated.call_args.kwargs["mass_kg"], 8.5)

    def test_missing_non_first_board_field_rejects_before_solver(self):
        data = copy.deepcopy(self.catalog._data)
        del data["aircraft"]["geoscan201"]["physics"]["battery_energy_wh"]
        s = _scenario()
        s["boards"] = [_board("Gemini", "geoscan-gemini", "geoscan-pf1b"),
                       _board("201", "geoscan-201", "riebo-r6")]
        symbols = dict(geo_mission._core_symbols(), get_default_catalog=lambda: Catalog(data))
        with patch.object(geo_mission, "_core_symbols", return_value=symbols):
            with self.assertRaisesRegex(ValueError, "geoscan201.*battery_energy"):
                mission_for(s)

    def test_model_direct_entry_wind_gate_before_geometry_even_precomputed(self):
        s = _scenario()
        mission, _ = mission_for(s)
        mission.params.wind.speed_mps = 11
        with patch.object(core_pipeline, "generate_swaths_for_area", side_effect=AssertionError("geometry called")):
            with self.assertRaisesRegex(ValueError, "exceeds max_wind"):
                core_pipeline._generate_all_swaths(mission, 0)
            with self.assertRaisesRegex(ValueError, "exceeds max_wind"):
                core_pipeline.run_one_angle(mission, 0, Counters(), swaths_by_area={}, h_agl_by_area={})

    def test_above_wind_returns_v0_error_without_solver_call(self):
        from planes.runtime.pipeline import run

        for external, camera, spectrum, internal, _ in SMOKES:
            s = _scenario()
            s["boards"] = [_board("wind-board", external, camera)]
            s["required_spectrum"] = spectrum
            s["wind"]["speed_ms"] = EXPECTED[internal][-1] + 0.01
            request = {"contract_version": "v0", "job_id": "cat001b_wind", "scenario": s,
                       "optimization": {"objective": "min_time", "time_limit_seconds": 30}, "seed": 7}
            with patch.object(geo_mission, "_acquire_dem", return_value=Path("test-only.tif")), \
                 patch.object(geo_mission, "_load_geotiff", return_value=FlatDEM()), \
                 patch.object(geo_mission, "_run_pipeline") as solver:
                response = run(json.dumps(request).encode("utf-8"))
            solver.assert_not_called()
            self.assertEqual(response.contract_version, "v0")
            self.assertEqual(response.outcome, "error")
            self.assertIsNone(response.mission_plan)
            self.assertIn("exceeds max_wind_m_s", "\n".join(response.solver_report.limitations))

    def test_three_representative_real_pipeline_characteristic_smokes(self):
        with tempfile.TemporaryDirectory(prefix="cat001b-") as td:
            dem = Path(td) / "synthetic-test-only.tif"
            dem.write_bytes(_geotiff_bytes(37.59, 55.74, 37.61, 55.76))
            for external, camera, spectrum, internal, core_camera in SMOKES:
                with self.subTest(model=internal):
                    s = _scenario()
                    s["survey_kml"] = SMALL_SURVEY
                    s["constraints_kml"] = ""
                    s["aerodromes"][0].update(lat=55.7500, lon=37.6000)
                    s["boards"] = [_board("characteristic-smoke", external, camera)]
                    s["required_spectrum"] = spectrum
                    s["wind"]["speed_ms"] = 1
                    # Use each camera's physical scale: 201 AGL >100 m and
                    # thermal AGL > existing 30 m safety floor; no generic optics.
                    s["gsd_cm_per_px"] = {"gemini": 3, "geoscan201": 1, "geoscan801": 6}[internal]
                    with patch.object(geo_mission, "_acquire_dem", return_value=dem), \
                         patch.object(geo_mission, "_log"), \
                         patch("planner.physics.factory._legacy_physics_params", side_effect=AssertionError("generic physics called")), \
                         patch.object(core_pipeline, "build_physics_params", wraps=build_physics_params) as resolved:
                        result = geo_mission.solve_envelope(Problem("cat001b", s, "min_time", 42, 90), time.monotonic()+90)
                    self.assertIsInstance(result, Solution)
                    self.assertTrue(result.mission_plan["routes"])
                    self.assertGreater(result.mission_plan["mission"]["total_flight_time_s"], 0)
                    self.assertGreater(resolved.call_count, 0)
                    for call in resolved.call_args_list:
                        config, catalog = call.args
                        self.assertEqual((config.model, config.camera_id), (internal, core_camera))
                        pp = build_physics_params(config, catalog)
                        self.assertEqual(tuple(getattr(pp, f) for f in PARAMS), EXPECTED[internal])
                        self.assertEqual(build_physics_model(pp).power_w(0, 0), 220 if internal == "geoscan201" else 90*pp.mass_kg)
                    self.assertTrue(any(f"aircraft {internal} reserve_fraction" in n for n in result.limitations))


if __name__ == "__main__":
    unittest.main()
