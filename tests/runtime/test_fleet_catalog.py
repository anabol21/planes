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
        self.assertEqual(gemini["descent_m_s"]["value"], 5)
        self.assertEqual(gemini["descent_m_s"]["mark"], "estimate")

    def test_201_estimates_and_calculated_energy(self) -> None:
        model = _by_id(_load()["uav_models"])["geoscan-201"]
        self.assertEqual(model["airspeed_m_s"]["value"], 25)
        self.assertEqual(model["airspeed_m_s"]["mark"], "estimate")
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
        self.assertEqual(model["descent_m_s"]["value"], 2)
        self.assertEqual(model["descent_m_s"]["mark"], "synthetic")
        self.assertNotIn("power_coeffs", model)
        self.assertNotIn("turn_time_s", model)

    def test_801_is_the_quadcopter(self) -> None:
        model = _by_id(_load()["uav_models"])["geoscan-801"]
        self.assertEqual(model["kind"], "quadcopter")
        self.assertEqual(model["mass_kg"]["value"], 1.5)
        self.assertEqual(model["airspeed_m_s"]["value"], 15)
        self.assertEqual(model["airspeed_m_s"]["mark"], "passport")
        self.assertEqual(model["climb_m_s"]["value"], 4)
        self.assertEqual(model["climb_m_s"]["mark"], "estimate")
        self.assertEqual(model["battery"]["energy_wh"]["value"], 126.28)
        self.assertEqual(model["battery"]["energy_wh"]["mark"], "passport")
        self.assertEqual(model["flight_time_s"]["value"], 2400)
        self.assertIsNone(model["payload_mass_kg"])
        self.assertEqual(model["descent_m_s"]["value"], 0.5)
        self.assertEqual(model["takeoff"], "vertical")
        self.assertEqual(model["landing"], "vertical")

    def test_derived_optics_keep_their_marks(self) -> None:
        cameras = _by_id(_load()["cameras"])
        pf1b = cameras["geoscan-pf1b"]
        for field in _OPTIC:
            self.assertTrue(_marked(pf1b[field], "passport"), field)
        pollux = cameras["geoscan-pollux"]
        self.assertEqual(pollux["sensor_width_mm"]["value"], 5.04)
        self.assertEqual(pollux["sensor_height_mm"]["value"], 3.78)
        self.assertTrue(_marked(pollux["sensor_width_mm"], "calculation"))
        self.assertIn("6.3 mm", pollux["sensor_width_mm"]["note"])
        self.assertEqual([band["value"] for band in pollux["bands"]], [470, 560, 668, 720, 840])
        for camera_id, width, height in (("riebo-r4", 8204, 5485), ("riebo-r6", 9552, 6386)):
            self.assertEqual(cameras[camera_id]["image_width_px"]["value"], width)
            self.assertEqual(cameras[camera_id]["image_height_px"]["value"], height)
            self.assertTrue(_marked(cameras[camera_id]["image_width_px"], "calculation"))
            self.assertTrue(cameras[camera_id]["image_width_px"]["note"])
        umc = cameras["sony-umc-r10c-16"]
        self.assertEqual(umc["focal_length_mm"]["value"], 16)
        self.assertTrue(_marked(umc["focal_length_mm"], "estimate"))
        self.assertEqual(cameras["sony-umc-r10c-20"]["focal_length_mm"]["value"], 20)
        for camera_id in ("sony-dsc-rx1rm2", "sony-dsc-rx1rm3"):
            camera = cameras[camera_id]
            self.assertEqual(camera["focal_length_mm"]["value"], 35)
            self.assertTrue(_marked(camera["image_width_px"], "estimate"))
            self.assertEqual(camera["gaps"], [])
        zv = cameras["sony-zv-e10"]
        self.assertIsNone(zv["focal_length_mm"])
        self.assertEqual(zv["gaps"], ["focal_length_mm"])
        self.assertIn("selected mission lens", zv["live_geometry_error"])
        visible = cameras["geoscan-801-visible-4-35"]
        self.assertEqual(visible["sensor_width_mm"]["value"], 6.17)
        self.assertEqual(visible["sensor_height_mm"]["value"], 4.55)
        self.assertTrue(_marked(visible["sensor_width_mm"], "estimate"))
        self.assertIn("1/2.3", visible["sensor_width_mm"]["note"])
        self.assertEqual(visible["image_width_px"]["mark"], "estimate")
        thermal = cameras["geoscan-801-thermal"]
        self.assertEqual(thermal["spectra"], ["infrared"])
        self.assertEqual(thermal["pixel_pitch_um"]["value"], 17)
        self.assertTrue(_marked(thermal["pixel_pitch_um"], "estimate"))
        self.assertEqual(thermal["sensor_width_mm"]["value"], 10.88)
        self.assertEqual(thermal["sensor_height_mm"]["value"], 8.704)
        self.assertTrue(_marked(thermal["sensor_width_mm"], "calculation"))
        self.assertIn("17 um", thermal["sensor_width_mm"]["note"])


if __name__ == "__main__":
    unittest.main()
