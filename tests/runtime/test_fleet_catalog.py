"""Fleet catalog records filled from Grisha's data.json, with marks on every number."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "runtime"
    / "catalog"
    / "fleet_catalog.json"
)

_OPTIC = (
    "sensor_width_mm",
    "sensor_height_mm",
    "focal_length_mm",
    "image_width_px",
    "image_height_px",
)


def _load() -> dict:
    return json.loads(_CATALOG.read_text(encoding="utf-8"))


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows}


def _marked(value: object, mark: str) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("value"), (int, float))
        and not isinstance(value.get("value"), bool)
        and value.get("mark") == mark
    )


class FleetCatalogTest(unittest.TestCase):
    def test_catalog_version_is_1(self) -> None:
        self.assertEqual(_load()["catalog_version"], 1)

    def test_ids_are_unique(self) -> None:
        catalog = _load()
        uav_ids = [row["id"] for row in catalog["uav_models"]]
        camera_ids = [row["id"] for row in catalog["cameras"]]
        self.assertEqual(len(uav_ids), len(set(uav_ids)))
        self.assertEqual(len(camera_ids), len(set(camera_ids)))
        self.assertEqual(
            set(uav_ids),
            {"geoscan-gemini", "geoscan-201", "geoscan-801"},
        )
        self.assertEqual(
            set(camera_ids),
            {
                "geoscan-pf1b",
                "sony-umc-r10c-16",
                "sony-umc-r10c-20",
                "geoscan-pollux",
                "riebo-r4",
                "riebo-r6",
                "sony-dsc-rx1rm2",
                "sony-dsc-rx1rm3",
                "sony-zv-e10",
                "geoscan-801-visible-4-35",
                "geoscan-801-visible-16",
                "geoscan-801-thermal",
            },
        )
        self.assertNotIn("sony-a6000", camera_ids)
        self.assertNotIn("sony-umc-r10c", camera_ids)

    def test_every_compatibility_id_exists(self) -> None:
        catalog = _load()
        uav_ids = {row["id"] for row in catalog["uav_models"]}
        camera_ids = {row["id"] for row in catalog["cameras"]}
        self.assertEqual(len(catalog["compatibility"]), 13)
        pairs = {(edge["uav_model_id"], edge["camera_id"]) for edge in catalog["compatibility"]}
        self.assertNotIn(("geoscan-801", "sony-a6000"), pairs)
        self.assertNotIn(("geoscan-801", "geoscan-pollux"), pairs)
        self.assertIn(("geoscan-801", "geoscan-801-thermal"), pairs)
        self.assertIn(("geoscan-gemini", "sony-umc-r10c-16"), pairs)
        self.assertIn(("geoscan-gemini", "sony-umc-r10c-20"), pairs)
        for edge in catalog["compatibility"]:
            self.assertIn(edge["uav_model_id"], uav_ids)
            self.assertIn(edge["camera_id"], camera_ids)
            self.assertIsInstance(edge["source"], str)
            self.assertTrue(edge["source"])

    def test_gemini_keeps_passport_speed_beside_the_estimate(self) -> None:
        gemini = _by_id(_load()["uav_models"])["geoscan-gemini"]
        self.assertNotIn("usable_by_current_solver", gemini)
        self.assertTrue(_marked(gemini["mass_kg"], "passport"))
        self.assertEqual(gemini["airspeed_m_s"]["value"], 15)
        self.assertEqual(gemini["airspeed_m_s"]["mark"], "passport")
        self.assertEqual(gemini["airspeed_estimate_m_s"]["value"], 12)
        self.assertEqual(gemini["airspeed_estimate_m_s"]["mark"], "estimate")
        self.assertTrue(_marked(gemini["battery"]["energy_wh"], "passport"))
        self.assertEqual(gemini["battery"]["energy_wh"]["value"], 144.7)
        self.assertEqual(gemini["power_coeffs"]["kh"]["value"], 90)
        self.assertEqual(gemini["turn_time_s"][0]["value"], 5)
        self.assertIsNone(gemini["payload_mass_kg"])
        self.assertIsNone(gemini["descent_m_s"])

    def test_201_estimates_and_calculated_energy(self) -> None:
        model = _by_id(_load()["uav_models"])["geoscan-201"]
        self.assertEqual(model["airspeed_m_s"], {"value": 25, "mark": "estimate", "note": "середина диапазона 18–36 м/с"})
        self.assertTrue(_marked(model["climb_m_s"], "estimate"))
        self.assertEqual(model["climb_m_s"]["value"], 3)
        self.assertTrue(_marked(model["battery"]["energy_wh"], "calculation"))
        self.assertEqual(model["battery"]["energy_wh"]["value"], 740)
        self.assertEqual(model["power_const_w"]["value"], 220)
        self.assertEqual(model["stall_speed_m_s"]["value"], 15)
        self.assertEqual(model["turn_radius_m"]["value"], 110)
        self.assertEqual(model["turn_radius_m"]["mark"], "calculation")
        self.assertEqual(model["catapult_time_s"]["value"], 10)
        self.assertEqual(model["parachute_time_s"]["value"], 120)
        self.assertEqual(model["takeoff"], "catapult")
        self.assertEqual(model["landing"], "parachute")
        self.assertIsNone(model["descent_m_s"])
        self.assertNotIn("power_coeffs", model)
        self.assertNotIn("turn_time_s", model)

    def test_801_is_the_quadcopter(self) -> None:
        model = _by_id(_load()["uav_models"])["geoscan-801"]
        self.assertEqual(model["kind"], "quadcopter")
        self.assertEqual(model["mass_kg"]["value"], 1.5)
        self.assertEqual(model["airspeed_m_s"]["value"], 15)
        self.assertEqual(model["airspeed_m_s"]["mark"], "passport")
        self.assertEqual(model["climb_m_s"], {"value": 4, "mark": "estimate"})
        self.assertEqual(model["battery"]["energy_wh"]["value"], 90)
        self.assertEqual(model["battery"]["energy_wh"]["mark"], "estimate")
        self.assertEqual(model["flight_time_s"]["value"], 2400)
        self.assertIsNone(model["payload_mass_kg"])
        self.assertIsNone(model["descent_m_s"])
        self.assertIsNone(model["takeoff"])
        self.assertIsNone(model["landing"])

    def test_derived_optics_keep_their_marks(self) -> None:
        cameras = _by_id(_load()["cameras"])
        pf1b = cameras["geoscan-pf1b"]
        for field in _OPTIC:
            self.assertTrue(_marked(pf1b[field], "passport"), field)
        pollux = cameras["geoscan-pollux"]
        self.assertEqual(pollux["sensor_width_mm"], {"value": 5.04, "mark": "calculation"})
        self.assertEqual(pollux["sensor_height_mm"], {"value": 3.78, "mark": "calculation"})
        self.assertIn("6.3 mm", pollux["source"])
        self.assertEqual([band["value"] for band in pollux["bands"]], [470, 560, 668, 720, 840])
        self.assertEqual(cameras["riebo-r4"]["image_width_px"], {"value": 8204, "mark": "calculation"})
        self.assertEqual(cameras["riebo-r4"]["image_height_px"], {"value": 5485, "mark": "calculation"})
        self.assertEqual(cameras["riebo-r6"]["image_width_px"], {"value": 9552, "mark": "calculation"})
        self.assertEqual(cameras["riebo-r6"]["image_height_px"], {"value": 6386, "mark": "calculation"})
        umc = cameras["sony-umc-r10c-16"]
        self.assertEqual(umc["focal_length_mm"], {"value": 16, "mark": "estimate"})
        self.assertEqual(cameras["sony-umc-r10c-20"]["focal_length_mm"]["value"], 20)
        for camera_id in ("sony-dsc-rx1rm2", "sony-dsc-rx1rm3", "sony-zv-e10"):
            camera = cameras[camera_id]
            self.assertIsNone(camera["focal_length_mm"])
            self.assertIsNone(camera["image_width_px"])
            self.assertIn("focal_length_mm", camera["gaps"])
        visible = cameras["geoscan-801-visible-4-35"]
        self.assertIsNone(visible["sensor_width_mm"])
        self.assertIsNone(visible["sensor_height_mm"])
        self.assertIn("1/2.3", visible["source"])
        self.assertEqual(visible["image_width_px"]["mark"], "estimate")
        thermal = cameras["geoscan-801-thermal"]
        self.assertEqual(thermal["spectra"], ["infrared"])
        self.assertEqual(thermal["pixel_pitch_um"], {"value": 17, "mark": "calculation", "note": "типовое для класса 640 × 512"})
        self.assertEqual(thermal["sensor_width_mm"], {"value": 10.88, "mark": "calculation"})
        self.assertEqual(thermal["sensor_height_mm"], {"value": 8.704, "mark": "calculation"})
        self.assertIn("8–14", thermal["source"])


if __name__ == "__main__":
    unittest.main()
