"""CAT-001C catalog at catalog/fleet_catalog.json (iso worker source)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "fleet_catalog.json"


def _load() -> dict:
    return json.loads(_CATALOG.read_text(encoding="utf-8"))


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows}


class Cat001cCatalogTest(unittest.TestCase):
    def test_file_is_present_and_versioned(self) -> None:
        self.assertTrue(_CATALOG.is_file())
        catalog = _load()
        self.assertEqual(catalog["catalog_version"], 1)
        models = _by_id(catalog["uav_models"])
        self.assertIn("geoscan-gemini", models)
        self.assertIn("geoscan-201", models)
        self.assertIn("geoscan-801", models)

    def test_iso_worker_reads_speed_and_reserve_not_battery_wh(self) -> None:
        gemini = _by_id(_load()["uav_models"])["geoscan-gemini"]
        self.assertEqual(gemini["survey_speed_m_s"]["value"], 12)
        self.assertEqual(gemini["reserve_fraction"]["value"], 0.05)
        self.assertEqual(gemini["airspeed_m_s"]["value"], 15)
        self.assertEqual(gemini["battery"]["energy_wh"]["value"], 144.7)
        self.assertIn("energy_wh", gemini["battery"])

    def test_pf1b_optics_are_present(self) -> None:
        cameras = _by_id(_load()["cameras"])
        pf1b = cameras["geoscan-pf1b"]
        for key in ("sensor_width_mm", "focal_length_mm", "image_width_px"):
            raw = pf1b[key]
            value = raw["value"] if isinstance(raw, dict) else raw
            self.assertGreater(float(value), 0.0)


if __name__ == "__main__":
    unittest.main()
