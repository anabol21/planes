"""Fleet catalog records, with the gaps the specification sheets left empty."""

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


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
                "sony-umc-r10c",
                "geoscan-pollux",
                "riebo-r4",
                "riebo-r6",
                "sony-dsc-rx1rm2",
                "sony-dsc-rx1rm3",
                "sony-zv-e10",
                "sony-a6000",
            },
        )

    def test_every_compatibility_id_exists(self) -> None:
        catalog = _load()
        uav_ids = {row["id"] for row in catalog["uav_models"]}
        camera_ids = {row["id"] for row in catalog["cameras"]}
        self.assertEqual(len(catalog["compatibility"]), 11)
        for edge in catalog["compatibility"]:
            self.assertIn(edge["uav_model_id"], uav_ids)
            self.assertIn(edge["camera_id"], camera_ids)
            self.assertIsInstance(edge["source"], str)
            self.assertTrue(edge["source"])

    def test_gemini_with_pf1b_fills_current_solver_fields(self) -> None:
        catalog = _load()
        gemini = _by_id(catalog["uav_models"])["geoscan-gemini"]
        pf1b = _by_id(catalog["cameras"])["geoscan-pf1b"]
        self.assertTrue(gemini["usable_by_current_solver"])
        self.assertTrue(_number(gemini["mass_kg"]))
        self.assertTrue(_number(gemini["airspeed_m_s"]))
        self.assertTrue(_number(gemini["climb_m_s"]))
        self.assertTrue(_number(gemini["max_wind_m_s"]))
        self.assertTrue(_number(gemini["flight_time_s"]))
        self.assertTrue(_number(gemini["battery"]["energy_wh"]))
        for field in _OPTIC:
            self.assertTrue(_number(pf1b[field]), field)
        paired = [
            edge
            for edge in catalog["compatibility"]
            if edge["uav_model_id"] == "geoscan-gemini"
            and edge["camera_id"] == "geoscan-pf1b"
        ]
        self.assertEqual(paired, [
            {
                "uav_model_id": "geoscan-gemini",
                "camera_id": "geoscan-pf1b",
                "source": "Geoscan Gemini specification sheet",
            }
        ])

    def test_geoscan_201_and_801_are_not_usable(self) -> None:
        uavs = _by_id(_load()["uav_models"])
        self.assertFalse(uavs["geoscan-201"]["usable_by_current_solver"])
        self.assertFalse(uavs["geoscan-801"]["usable_by_current_solver"])


if __name__ == "__main__":
    unittest.main()
