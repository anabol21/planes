"""CAT-001C: selectable fleet completeness and duplicate-catalog consistency."""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src/planes/model/itog_model/mvp_optimizator"
sys.path.insert(0, str(CORE / "src"))

from planner.camera import camera_params_from_catalog
from planner.io.catalog import get_default_catalog
from planner.models import UAVConfig
from planner.physics.factory import build_physics_model, build_physics_params
from planes.runtime import geo_mission

FLEET_PATH = ROOT / "src/planes/runtime/catalog/fleet_catalog.json"
MODEL_PATH = CORE / "data/data.json"
CAMERA_FIELDS = (
    "sensor_width_mm", "sensor_height_mm", "focal_length_mm",
    "image_width_px", "image_height_px",
)


def _null_paths(value: object, path: str = "$") -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [p for key, child in value.items() for p in _null_paths(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [p for i, child in enumerate(value) for p in _null_paths(child, f"{path}[{i}]")]
    return []


class LiveFleetCompletenessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fleet = json.loads(FLEET_PATH.read_text(encoding="utf-8"))
        cls.model_data = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        cls.catalog = get_default_catalog()

    def test_selectable_runtime_records_have_no_nulls_or_open_gaps(self) -> None:
        for group in ("uav_models", "cameras"):
            for row in self.fleet[group]:
                with self.subTest(group=group, record=row["id"]):
                    self.assertEqual(_null_paths(row), [])
                    self.assertEqual(row["gaps"], [])

    def test_all_selectable_mappings_and_13_pairs_resolve(self) -> None:
        self.assertEqual(len(self.fleet["compatibility"]), 13)
        self.assertEqual({row["id"] for row in self.fleet["uav_models"]}, set(geo_mission._MODEL_IDS))
        self.assertEqual({row["id"] for row in self.fleet["cameras"]}, set(geo_mission._CAMERA_IDS))
        uavs = {row["id"]: row for row in self.fleet["uav_models"]}
        cameras = {row["id"]: row for row in self.fleet["cameras"]}
        for edge in self.fleet["compatibility"]:
            ext_uav, ext_camera = edge["uav_model_id"], edge["camera_id"]
            with self.subTest(pair=(ext_uav, ext_camera)):
                model_id = geo_mission._translate_model(ext_uav, self.catalog)
                camera_id = geo_mission._translate_camera(ext_camera, self.catalog)
                aircraft = self.catalog.get_aircraft(model_id)
                camera = self.catalog.get_camera(camera_id)
                self.assertIn(camera_id, aircraft["related"]["cameras"])
                self.assertIn(model_id, camera["for"])
                params = camera_params_from_catalog(camera)
                self.assertTrue(all(math.isfinite(v) and v > 0 for v in params.values()))
                uav_config = UAVConfig(id="cat001c", model=model_id, camera_id=camera_id, vpp_id="cat001c")
                physics = build_physics_params(uav_config, self.catalog)
                build_physics_model(physics)
                self.assertIn(ext_camera, cameras)
                self.assertIn(ext_uav, uavs)

    def test_camera_values_and_spectral_metadata_mirror_model_source(self) -> None:
        for row in self.fleet["cameras"]:
            internal = geo_mission._CAMERA_IDS[row["id"]]
            geometry = self.catalog.get_camera(internal)["geometry"]
            with self.subTest(camera=row["id"]):
                for field in CAMERA_FIELDS:
                    self.assertEqual(row[field]["value"], geometry[field]["value"], field)
                if not row["bands"]:
                    self.assertIn("not applicable", row["bands_note"])
                else:
                    self.assertEqual(internal, "pollux")
                    model_bands = self.model_data["cameras"][internal]["specs"]["spectral_bands"]
                    self.assertEqual([band["value"] for band in row["bands"]],
                                     [band["wavelength_nm"] for band in model_bands])
        thermal = next(row for row in self.fleet["cameras"] if row["id"] == "geoscan-801-thermal")
        model_thermal = self.model_data["cameras"]["801-thermal"]
        self.assertEqual(thermal["spectral_range_um"]["value"], model_thermal["spectral_range_um"]["value"])
        self.assertEqual(thermal["spectral_range_um"]["mark"], "passport")

    def test_payload_semantics_and_batteries_are_synchronized_without_mass_change(self) -> None:
        runtime_uavs = {row["id"]: row for row in self.fleet["uav_models"]}
        for external, model_id in geo_mission._MODEL_IDS.items():
            runtime = runtime_uavs[external]
            aircraft = self.catalog.get_aircraft(model_id)
            if external == "geoscan-gemini":
                payload = runtime["payload_mass_kg"]
                self.assertEqual(payload["value"], aircraft["catalog_metadata"]["payload_mass_kg"]["value"])
                self.assertEqual(payload["mark"], "synthetic")
                self.assertTrue(payload["source"] and payload["note"])
            elif external == "geoscan-201":
                payload = runtime["payload_mass_kg"]
                self.assertEqual(payload["value"], aircraft["catalog_metadata"]["payload_mass_kg"]["value"])
                self.assertEqual(payload["mark"], "passport")
                self.assertIn("never add", aircraft["catalog_metadata"]["payload_mass_kg"]["note"])
            elif external == "geoscan-801":
                self.assertEqual(runtime["payload_mass_kg"]["status"], "not_applicable")
                self.assertEqual(runtime["payload_mass_kg"], aircraft["catalog_metadata"]["payload_mass_kg"])
            battery_id = aircraft["physics"]["battery_id"]
            battery = self.model_data["batteries"][battery_id]["specs"]["power"]
            self.assertEqual(runtime["battery"]["chemistry"], battery["chemistry"])
            for runtime_field, model_field in (("nominal_voltage_v", "nominal_voltage_v"),
                                               ("capacity_ah", "capacity_ah"),
                                               ("energy_wh", "energy_wh_numeric")):
                self.assertEqual(runtime["battery"][runtime_field]["value"], battery[model_field]["value"],
                                 (external, runtime_field))
                self.assertTrue(runtime["battery"][runtime_field]["source"])
                self.assertTrue(battery[model_field]["source"])

    def test_zv_is_explicitly_runnable_with_assumed_lens_configuration(self) -> None:
        runtime = next(row for row in self.fleet["cameras"] if row["id"] == "sony-zv-e10")
        camera = self.catalog.get_camera("zv-e10")
        geometry = camera["geometry"]
        self.assertEqual(tuple(geometry[field]["value"] for field in CAMERA_FIELDS), (23.5, 15.6, 16, 6000, 4000))
        self.assertEqual(geometry["focal_length_mm"]["mark"], "synthetic")
        self.assertIn("not body property", geometry["focal_length_mm"]["note"])
        self.assertEqual(runtime["gaps"], [])
        self.assertIn("16 mm", runtime["lens_configuration"])


if __name__ == "__main__":
    unittest.main()
