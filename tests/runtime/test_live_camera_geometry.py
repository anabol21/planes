"""CAT-001A: real catalogs, mapping, strict parser and unchanged GSD formulas."""

from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/planes/model/itog_model/mvp_optimizator"
sys.path.insert(0, str(CORE / "src"))

from planner.camera import camera_params_from_catalog
from planner.geometry.generate import _camera_params_from_catalog, compute_flight_and_swath
from planner.io.catalog import get_default_catalog
from planner.io.dem import FlatDEM
from planes.runtime import geo_mission
from planes.integration.kml.constraints import parse_survey_polygon
from tests.runtime.test_stitch_audit_seams import _board, _scenario, _SURVEY


EXPECTED = {
    "pf1b": (23.5, 15.6, 20, 6000, 4000),
    "umc-r10c-16": (23.2, 15.4, 16, 5456, 3632),
    "umc-r10c-20": (23.2, 15.4, 20, 5456, 3632),
    "pollux": (5.04, 3.78, 8, 1440, 1080),
    "riebo-r4": (35.9, 24, 40, 8204, 5485),
    "riebo-r6": (35.9, 24, 40, 9552, 6386),
    "rx1rm2": (35.9, 24, 35, 7952, 5304),
    "rx1rm3": (35.7, 23.8, 35, 9504, 6336),
    "zv-e10": (23.5, 15.6, 16, 6000, 4000),
    "801-visible-4-35": (6.17, 4.55, 4.35, 4000, 3000),
    "801-visible-16": (6.17, 4.55, 16, 4000, 3000),
    "801-thermal": (10.88, 8.704, 9.1, 640, 512),
}
FIELDS = ("sensor_width_mm", "sensor_height_mm", "focal_length_mm",
          "image_width_px", "image_height_px")
PARAMS = ("sensor_w_mm", "sensor_h_mm", "focal_mm", "res_w_px", "res_h_px")


class LiveCameraGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = get_default_catalog()
        cls.fleet = json.loads((ROOT / "src/planes/runtime/catalog/fleet_catalog.json")
                               .read_text(encoding="utf-8"))

    def test_every_selectable_camera_has_an_explicit_model_record(self):
        selectable = {c["id"] for c in self.fleet["cameras"]}
        self.assertEqual(selectable, set(geo_mission._CAMERA_IDS))
        self.assertEqual(len(selectable), 12)
        for external in selectable:
            with self.subTest(camera=external):
                internal = geo_mission._CAMERA_IDS[external]
                camera = self.catalog.get_camera(internal)
                self.assertEqual(camera["id"], internal)
                self.assertIn("geometry", camera)
                self.assertEqual(geo_mission._translate_camera(external, self.catalog), internal)

    def test_every_compatibility_pair_builds_or_explicitly_rejects(self):
        for edge in self.fleet["compatibility"]:
            external = edge["camera_id"]
            model = geo_mission._MODEL_IDS[edge["uav_model_id"]]
            internal = geo_mission._CAMERA_IDS[external]
            with self.subTest(pair=(model, external)):
                record = self.catalog.get_camera(internal)
                self.assertIn(model, record["for"])
                self.assertIn(internal, self.catalog.get_aircraft(model)["related"]["cameras"])
                scenario = _scenario()
                runtime = next(c for c in self.fleet["cameras"] if c["id"] == external)
                scenario["required_spectrum"] = runtime["spectra"][0]
                scenario["boards"] = [_board("board", edge["uav_model_id"], external)]
                kwargs = dict(survey_polygons=parse_survey_polygon(_SURVEY), constraints=[],
                              dem_path=Path("synthetic-test.tif"), dem=FlatDEM())
                mission, notes = geo_mission._mission(scenario, **kwargs)
                self.assertEqual(mission.uavs[0].camera_id, internal)
                self.assertEqual(len(mission.uavs), 1)
                camera_params_from_catalog(record)
                if any(record["geometry"][f]["mark"] != "passport" for f in FIELDS):
                    self.assertTrue(any(f"camera {internal}" in n for n in notes))

    def test_all_geometry_parameters_are_camera_specific(self):
        for internal, expected in EXPECTED.items():
            with self.subTest(camera=internal):
                params = _camera_params_from_catalog(self.catalog.get_camera(internal))
                self.assertEqual(tuple(params[key] for key in PARAMS), expected)
                self.assertTrue(all(math.isfinite(v) and v > 0 for v in params.values()))
                self.assertIsInstance(params["res_w_px"], int)
                self.assertIsInstance(params["res_h_px"], int)
                self.assertLess(params["sensor_w_mm"], 100)

    def test_numeric_geometry_is_authoritative_not_stale_text(self):
        record = copy.deepcopy(self.catalog.get_camera("pf1b"))
        record["specs"] = {"general": {"sensor": "640x512"},
                           "performance": {"focal_length": "999 mm"}}
        self.assertEqual(tuple(_camera_params_from_catalog(record)[k] for k in PARAMS), EXPECTED["pf1b"])

    def test_runtime_duplicates_match_model_values_and_marks(self):
        for runtime in self.fleet["cameras"]:
            internal = geo_mission._CAMERA_IDS[runtime["id"]]
            geometry = self.catalog.get_camera(internal)["geometry"]
            for field in FIELDS:
                with self.subTest(camera=internal, field=field):
                    actual = runtime[field]
                    expected = geometry.get(field)
                    if expected is None:
                        self.assertIsNone(actual)
                    else:
                        self.assertEqual(actual["value"], expected["value"])
                        self.assertEqual(actual["mark"], expected["mark"])
                        if expected["mark"] != "passport":
                            self.assertTrue(expected.get("note"))

    def test_focal_configurations_change_altitude_with_existing_formula(self):
        for narrow, wide, ratio in (("umc-r10c-20", "umc-r10c-16", 20/16),
                                    ("801-visible-16", "801-visible-4-35", 16/4.35)):
            with self.subTest(configurations=(narrow, wide)):
                a = compute_flight_and_swath(2, _camera_params_from_catalog(self.catalog.get_camera(narrow)))
                b = compute_flight_and_swath(2, _camera_params_from_catalog(self.catalog.get_camera(wide)))
                self.assertGreater(a["h_agl_m"], b["h_agl_m"])
                self.assertAlmostEqual(a["h_agl_m"]/b["h_agl_m"], ratio)
                # At fixed GSD and equal pixel width, swath width does NOT depend on focal.
                self.assertEqual(a["swath_width_m"], b["swath_width_m"])

    def test_thermal_pixels_are_not_sensor_millimetres(self):
        params = _camera_params_from_catalog(self.catalog.get_camera("801-thermal"))
        self.assertAlmostEqual(params["sensor_w_mm"], 640 * 17 / 1000)
        self.assertAlmostEqual(params["sensor_h_mm"], 512 * 17 / 1000)
        self.assertEqual((params["res_w_px"], params["res_h_px"]), (640, 512))
        self.assertLess(params["sensor_w_mm"], 20)

    def test_calculations_are_reproducible(self):
        pollux = _camera_params_from_catalog(self.catalog.get_camera("pollux"))
        self.assertEqual(pollux["sensor_w_mm"], 6.3 * 4 / 5)
        self.assertEqual(pollux["sensor_h_mm"], 6.3 * 3 / 5)
        for internal, mp in (("riebo-r4", 45), ("riebo-r6", 61)):
            params = _camera_params_from_catalog(self.catalog.get_camera(internal))
            self.assertEqual(params["res_w_px"], round(math.sqrt(mp*1e6*35.9/24)))
            self.assertEqual(params["res_h_px"], round(math.sqrt(mp*1e6*24/35.9)))

    def test_unknown_and_ambiguous_cameras_never_get_defaults(self):
        for camera in ({}, {"id": "unknown"}, self.catalog.get_camera("umc-r10c"),
                       self.catalog.get_camera("801-visible")):
            with self.subTest(camera=camera.get("id")):
                with self.assertRaisesRegex(ValueError, "invalid geometry"):
                    _camera_params_from_catalog(camera)
        camera = copy.deepcopy(self.catalog.get_camera("zv-e10"))
        del camera["geometry"]["focal_length_mm"]
        with self.assertRaisesRegex(ValueError, "focal_length_mm"):
            _camera_params_from_catalog(camera)

    def test_missing_and_invalid_numeric_fields_fail_without_text_fallback(self):
        for field in ("sensor_width_mm", "focal_length_mm", "image_width_px", "image_height_px"):
            for invalid in (None, True, 0, -1, float("nan"), float("inf"), "20 mm"):
                camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
                camera["geometry"][field]["value"] = invalid
                with self.subTest(field=field, value=invalid), self.assertRaises(ValueError):
                    _camera_params_from_catalog(camera)
            camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
            del camera["geometry"][field]
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, field):
                _camera_params_from_catalog(camera)
        camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
        camera["geometry"]["image_width_px"]["value"] = 6000.5
        with self.assertRaisesRegex(ValueError, "integer"):
            _camera_params_from_catalog(camera)

    def test_invalid_normalized_geometry_and_units_are_explicit_errors(self):
        for value in (None, [], "6000x4000"):
            camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
            camera["geometry"] = value
            with self.subTest(geometry=value), self.assertRaisesRegex(ValueError, "geometry must be an object"):
                _camera_params_from_catalog(camera)
        camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
        camera["geometry"]["sensor_width_mm"]["value"] = 640
        with self.assertRaisesRegex(ValueError, "pixel counts are not sensor millimetres"):
            _camera_params_from_catalog(camera)
        camera["geometry"]["sensor_width_mm"] = {"value": 23.5, "mark": "unverified"}
        with self.assertRaisesRegex(ValueError, "unmarked"):
            _camera_params_from_catalog(camera)
        # Height is metadata, not a newly invented requirement of the current formulas.
        camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
        del camera["geometry"]["sensor_height_mm"]
        params = _camera_params_from_catalog(camera)
        self.assertNotIn("sensor_h_mm", params)
        self.assertGreater(compute_flight_and_swath(2, params)["h_agl_m"], 0)

    def test_complete_text_records_work_but_ambiguous_units_do_not(self):
        camera = copy.deepcopy(self.catalog.get_camera("pf1b"))
        del camera["geometry"]
        camera["specs"]["general"]["max_resolution"] = "6000 × 4000"
        self.assertEqual(tuple(_camera_params_from_catalog(camera)[k] for k in PARAMS), EXPECTED["pf1b"])
        camera["specs"]["performance"]["focal_length"] = "16 или 20 mm"
        with self.assertRaisesRegex(ValueError, "one explicit focal"):
            _camera_params_from_catalog(camera)
        camera["specs"]["performance"]["focal_length"] = "20 mm"
        camera["specs"]["general"]["sensor_size"] = "640x512"
        with self.assertRaisesRegex(ValueError, "physical sensor"):
            _camera_params_from_catalog(camera)

    def test_selectable_second_camera_is_validated_without_changing_shared_geometry(self):
        scenario = _scenario()
        scenario["boards"].append(_board("zv", "geoscan-201", "sony-zv-e10"))
        mission, _ = geo_mission._mission(
            scenario, survey_polygons=parse_survey_polygon(_SURVEY),
            constraints=[], dem_path=Path("synthetic-test.tif"), dem=FlatDEM())
        self.assertEqual(len(mission.uavs), 2)
        self.assertEqual(mission.uavs[1].camera_id, "zv-e10")

    def test_zv_e10_explicit_lens_builds_a_mission(self):
        scenario = _scenario()
        scenario["boards"] = [_board("body", "geoscan-201", "sony-zv-e10")]
        mission, notes = geo_mission._mission(
            scenario, survey_polygons=parse_survey_polygon(_SURVEY), constraints=[],
            dem_path=Path("synthetic-test.tif"), dem=FlatDEM())
        self.assertEqual(mission.uavs[0].camera_id, "zv-e10")
        self.assertTrue(any("camera zv-e10" in note for note in notes))

    def test_existing_survey_types_remain_unchanged(self):
        for spectrum, model, camera, survey_type in (
            ("RGB", "geoscan-gemini", "geoscan-pollux", "visible"),
            ("multispectral", "geoscan-gemini", "geoscan-pollux", "multispectral"),
            ("infrared", "geoscan-801", "geoscan-801-thermal", "thermal"),
        ):
            scenario = _scenario()
            scenario["required_spectrum"] = spectrum
            scenario["boards"] = [_board("board", model, camera)]
            with self.subTest(spectrum=spectrum):
                mission, _notes = geo_mission._mission(
                    scenario, survey_polygons=parse_survey_polygon(_SURVEY), constraints=[],
                    dem_path=Path("synthetic-test.tif"), dem=FlatDEM())
                self.assertEqual(mission.areas[0].survey_type.value, survey_type)
        for spectrum in ("LiDAR", "geophysical"):
            scenario = _scenario()
            scenario["required_spectrum"] = spectrum
            with self.subTest(spectrum=spectrum), self.assertRaisesRegex(ValueError, "not accepted"):
                geo_mission._mission(scenario, survey_polygons=parse_survey_polygon(_SURVEY),
                                     constraints=[], dem_path=Path("synthetic-test.tif"), dem=FlatDEM())

    def test_shared_swath_limitation_is_first_uav_and_is_disclosed(self):
        from planner.solver import pipeline

        scenario = _scenario()
        scenario["boards"].append(_board("umc", "geoscan-gemini", "sony-umc-r10c-20"))
        mission, notes = geo_mission._mission(
            scenario, survey_polygons=parse_survey_polygon(_SURVEY), constraints=[],
            dem_path=Path("synthetic-test.tif"), dem=FlatDEM())
        self.assertTrue(any("first admitted UAV camera" in n for n in notes))
        with patch.object(pipeline, "generate_swaths_for_area", return_value=([], 1)) as generate:
            pipeline._generate_all_swaths(mission, 0)
            self.assertEqual(generate.call_args.kwargs["camera"]["id"], "pf1b")
            swapped = mission.model_copy(update={"uavs": list(reversed(mission.uavs))})
            pipeline._generate_all_swaths(swapped, 0)
            self.assertEqual(generate.call_args.kwargs["camera"]["id"], "umc-r10c-20")


if __name__ == "__main__":
    unittest.main()
