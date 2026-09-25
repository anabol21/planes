"""Regression and integration tests for terrain-aware precompute."""

from pathlib import Path
import unittest

import numpy as np

from optimizer.models import InputData
from optimizer.precompute import (
    bearing_deg,
    ground_speed,
    haversine_m,
    power_w,
    precompute,
)
from optimizer.terrain import ElevationPoint, InMemoryTerrainProvider


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EXPECTED_PRE_KEYS = {
    "M", "N", "entries", "exits", "d", "t_pure", "t", "e",
    "tau", "eps", "T_takeoff", "T_landing", "E_takeoff",
    "E_landing", "T_max", "E_max", "altitude_m", "P_const",
    "order_key",
}


def make_input(*, terrain: bool = False) -> InputData:
    payload = {
        "criterion": "min_flight_hours",
        "gsd_cm_per_px": 3.0,
        "wind": {"speed_ms": 5.0, "direction_deg": 270.0},
        "area": [
            [37.0000, 55.0000],
            [37.0020, 55.0000],
            [37.0020, 55.0010],
            [37.0000, 55.0010],
            [37.0000, 55.0000],
        ],
        "takeoff": {"lat": 55.0, "lon": 37.0},
        "uav": {
            "model": "Synthetic UAV",
            "count": 2,
            "mass_kg": 2.0,
            "max_flight_time_s": 2400.0,
            "battery_wh": 144.7,
            "v_air_ms": 12.0,
            "v_vertical_ms": 5.0,
            "max_wind_ms": 10.0,
        },
        "camera": {
            "sensor_width_mm": 23.5,
            "sensor_height_mm": 15.6,
            "focal_length_mm": 20.0,
            "image_width_px": 6000,
            "image_height_px": 4000,
        },
        "survey": {
            "forward_overlap": 0.7,
            "side_overlap": 0.6,
            "strip_direction_deg": 90.0,
        },
        "power_coeffs": {"kh": 90.0, "kv": 0.02, "kw": 0.008},
        "solver": {
            "time_limit_s": 60,
            "turn_time_s": 5.0,
            "apply_turn_to_base": False,
        },
    }
    if terrain:
        payload["terrain"] = {
            "kml_path": str(DATA_DIR / "terrain_synthetic.kml"),
            "crs": "EPSG:4326",
            "horizontal_unit": "degree",
            "elevation_unit": "metre",
            "sample_step_m": 25.0,
        }
    return InputData(**payload)


class LegacyPrecomputeTests(unittest.TestCase):
    def test_no_terrain_matches_legacy_arrays_and_budgets(self) -> None:
        data = make_input()
        strip = ((55.0, 37.0), (55.0, 37.0012))
        altitude_m = 150.0
        result = precompute(data, [strip], altitude_m)

        distance = haversine_m(*strip[0], *strip[1])
        strip_bearing = bearing_deg(*strip[0], *strip[1])
        strip_speed = max(
            ground_speed(
                data.uav.v_air_ms,
                strip_bearing,
                data.wind.speed_ms,
                data.wind.direction_deg,
            ),
            0.5,
        )
        expected_tau = distance / strip_speed
        expected_power = power_w(
            data.uav.mass_kg,
            data.uav.v_air_ms,
            data.wind.speed_ms,
            data.power_coeffs.kh,
            data.power_coeffs.kv,
            data.power_coeffs.kw,
        )

        expected_d = np.array([[0.0, 0.0], [distance, 0.0]])
        return_bearing = bearing_deg(*strip[1], *strip[0])
        return_speed = max(
            ground_speed(
                data.uav.v_air_ms,
                return_bearing,
                data.wind.speed_ms,
                data.wind.direction_deg,
            ),
            0.5,
        )
        expected_t_pure = np.array(
            [[0.0, 0.0], [distance / return_speed, 0.0]]
        )

        np.testing.assert_allclose(result["d"], expected_d, rtol=0.0, atol=1e-9)
        np.testing.assert_allclose(
            result["t_pure"], expected_t_pure, rtol=0.0, atol=1e-9
        )
        np.testing.assert_allclose(result["t"], expected_t_pure)
        np.testing.assert_allclose(
            result["e"], expected_power * expected_t_pure / 3600.0
        )
        self.assertAlmostEqual(result["tau"][0], expected_tau)
        self.assertAlmostEqual(
            result["eps"][0], expected_power * expected_tau / 3600.0
        )
        self.assertEqual(result["T_takeoff"], 30.0)
        self.assertEqual(result["T_landing"], 30.0)
        self.assertEqual(result["T_max"], 2340.0)
        self.assertAlmostEqual(result["E_max"], 141.7)
        self.assertEqual(set(result), EXPECTED_PRE_KEYS)

    def test_legacy_input_has_no_implicit_reserve(self) -> None:
        result = precompute(
            make_input(), [((55.0, 37.0), (55.0, 37.0004))], 150.0
        )
        self.assertEqual(result["T_max"], 2400.0 - 60.0)
        self.assertAlmostEqual(result["E_max"], 144.7 - 3.0)


class TerrainPrecomputeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strips = [
            ((55.0, 37.0000), (55.0, 37.0012)),
            ((55.0, 37.0020), (55.0, 37.0016)),
        ]

    def test_kml_terrain_changes_supported_survey_and_transfer_costs(self) -> None:
        flat = precompute(make_input(), self.strips, 150.0)
        terrain = precompute(make_input(terrain=True), self.strips, 150.0)

        self.assertGreater(terrain["tau"][0], flat["tau"][0])
        self.assertGreater(terrain["eps"][0], flat["eps"][0])
        self.assertGreater(terrain["d"][1, 2], flat["d"][1, 2])
        self.assertGreater(terrain["t_pure"][1, 2], flat["t_pure"][1, 2])
        self.assertGreater(terrain["e"][1, 2], flat["e"][1, 2])
        self.assertEqual(set(terrain), EXPECTED_PRE_KEYS)

    def test_terrain_policy_applies_configured_ten_percent_reserve(self) -> None:
        terrain = precompute(make_input(terrain=True), self.strips, 150.0)
        expected_time = 2400.0 * 0.90 - 60.0
        expected_energy = 144.7 * 0.90 - 3.0

        self.assertAlmostEqual(terrain["T_max"], expected_time)
        self.assertAlmostEqual(terrain["E_max"], expected_energy)

    def test_wind_definition_remains_constant_vector(self) -> None:
        data = make_input(terrain=True)
        terrain = precompute(data, self.strips, 150.0)
        bearing = bearing_deg(*self.strips[0][0], *self.strips[0][1])
        expected_speed = max(
            ground_speed(
                data.uav.v_air_ms,
                bearing,
                data.wind.speed_ms,
                data.wind.direction_deg,
            ),
            0.5,
        )

        terrain_length = terrain["tau"][0] * expected_speed
        self.assertAlmostEqual(
            terrain["eps"][0], terrain["P_const"] * terrain["tau"][0] / 3600.0
        )
        self.assertGreater(
            terrain_length,
            haversine_m(*self.strips[0][0], *self.strips[0][1]),
        )

    def test_injected_provider_is_deterministic_and_offline(self) -> None:
        provider = InMemoryTerrainProvider(
            (
                ElevationPoint(37.0000, 55.0, 100.0),
                ElevationPoint(37.0012, 55.0, 180.0),
                ElevationPoint(37.0020, 55.0, 100.0),
            )
        )
        first = precompute(
            make_input(terrain=True), self.strips, 150.0, terrain_provider=provider
        )
        second = precompute(
            make_input(terrain=True), self.strips, 150.0, terrain_provider=provider
        )

        for key in ("d", "t_pure", "t", "e", "tau", "eps"):
            np.testing.assert_array_equal(first[key], second[key])


if __name__ == "__main__":
    unittest.main()
