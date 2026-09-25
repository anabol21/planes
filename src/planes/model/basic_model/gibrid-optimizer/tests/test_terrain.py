"""Deterministic tests for terrain providers and AGL profiling."""

from math import ceil, isclose
from pathlib import Path
import unittest

from optimizer.terrain import (
    ElevationPoint,
    FlatTerrainProvider,
    InMemoryTerrainProvider,
    KMLTerrainProvider,
    TerrainDataError,
    build_agl_profile,
    haversine_m,
    sample_segment,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class CountingFlatProvider(FlatTerrainProvider):
    def __init__(self, elevation_m: float) -> None:
        super().__init__(elevation_m)
        self.calls = 0

    def elevation_m(self, lon_deg: float, lat_deg: float) -> float:
        self.calls += 1
        return super().elevation_m(lon_deg, lat_deg)


class InvalidProvider:
    def __init__(self, value: object) -> None:
        self.value = value

    def elevation_m(self, lon_deg: float, lat_deg: float) -> object:
        return self.value


class TerrainProfileTests(unittest.TestCase):
    def test_flat_provider_keeps_constant_agl_without_vertical_distance(self) -> None:
        start = (55.0, 37.0)
        end = (55.0, 37.001)
        profile = build_agl_profile(
            start, end, FlatTerrainProvider(elevation_m=100.0), 150.0, 25.0
        )

        self.assertTrue(profile.samples)
        self.assertTrue(
            all(sample.terrain_elevation_m == 100.0 for sample in profile.samples)
        )
        self.assertTrue(
            all(sample.required_altitude_m == 250.0 for sample in profile.samples)
        )
        self.assertAlmostEqual(
            profile.distance_3d_m, profile.horizontal_distance_m, places=9
        )

    def test_rising_terrain_raises_absolute_altitude_at_constant_agl(self) -> None:
        provider = InMemoryTerrainProvider(
            (
                ElevationPoint(0.000, 0.0, 100.0),
                ElevationPoint(0.001, 0.0, 120.0),
                ElevationPoint(0.002, 0.0, 160.0),
            )
        )
        profile = build_agl_profile(
            (0.0, 0.000), (0.0, 0.002), provider, 150.0, 120.0
        )

        self.assertEqual(
            [sample.required_altitude_m for sample in profile.samples],
            [250.0, 270.0, 310.0],
        )

    def test_falling_terrain_lowers_absolute_altitude_at_constant_agl(self) -> None:
        provider = InMemoryTerrainProvider(
            (
                ElevationPoint(0.000, 0.0, 160.0),
                ElevationPoint(0.001, 0.0, 120.0),
                ElevationPoint(0.002, 0.0, 100.0),
            )
        )
        profile = build_agl_profile(
            (0.0, 0.000), (0.0, 0.002), provider, 150.0, 120.0
        )

        self.assertEqual(
            [sample.required_altitude_m for sample in profile.samples],
            [310.0, 270.0, 250.0],
        )

    def test_hill_profile_is_longer_than_horizontal_route(self) -> None:
        provider = InMemoryTerrainProvider(
            (
                ElevationPoint(0.000, 0.0, 100.0),
                ElevationPoint(0.001, 0.0, 180.0),
                ElevationPoint(0.002, 0.0, 100.0),
            )
        )
        profile = build_agl_profile(
            (0.0, 0.000), (0.0, 0.002), provider, 150.0, 120.0
        )

        self.assertEqual(
            [sample.required_altitude_m for sample in profile.samples],
            [250.0, 330.0, 250.0],
        )
        self.assertGreater(profile.distance_3d_m, profile.horizontal_distance_m)

    def test_sampling_uses_configured_step_and_includes_endpoints(self) -> None:
        start = (0.0, 0.0)
        end = (0.0, 0.001)
        distance = haversine_m(*start, *end)
        provider = CountingFlatProvider(10.0)
        profile = build_agl_profile(start, end, provider, 50.0, 25.0)
        expected_count = ceil(distance / 25.0) + 1

        self.assertEqual(len(profile.samples), expected_count)
        self.assertEqual(provider.calls, expected_count)
        self.assertEqual(
            (profile.samples[0].lat_deg, profile.samples[0].lon_deg), start
        )
        self.assertEqual(
            (profile.samples[-1].lat_deg, profile.samples[-1].lon_deg), end
        )
        self.assertLess(provider.calls, distance / 2.0)

    def test_sampling_rejects_non_positive_step(self) -> None:
        with self.assertRaises(ValueError):
            sample_segment((0.0, 0.0), (0.0, 0.001), 0.0)

    def test_missing_and_non_finite_elevation_fail_closed(self) -> None:
        for value in (None, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(TerrainDataError):
                    build_agl_profile(
                        (0.0, 0.0),
                        (0.0, 0.001),
                        InvalidProvider(value),
                        100.0,
                        25.0,
                    )


class KMLTerrainProviderTests(unittest.TestCase):
    def test_synthetic_kml_loads_flat_rise_hill_and_fall(self) -> None:
        provider = KMLTerrainProvider.from_file(
            DATA_DIR / "terrain_synthetic.kml",
            crs="EPSG:4326",
            horizontal_unit="degree",
            elevation_unit="metre",
        )

        expected = [100.0, 100.0, 140.0, 180.0, 140.0, 100.0]
        actual = [
            provider.elevation_m(37.0000 + index * 0.0004, 55.0)
            for index in range(6)
        ]
        self.assertEqual(actual, expected)
        self.assertTrue(isclose(provider.elevation_m(37.0010, 55.0), 160.0))

    def test_kml_requires_explicit_supported_crs_and_units(self) -> None:
        path = DATA_DIR / "terrain_synthetic.kml"
        invalid_cases = (
            {"crs": "", "horizontal_unit": "degree", "elevation_unit": "metre"},
            {"crs": "EPSG:3857", "horizontal_unit": "degree", "elevation_unit": "metre"},
            {"crs": "EPSG:4326", "horizontal_unit": "metre", "elevation_unit": "metre"},
            {"crs": "EPSG:4326", "horizontal_unit": "degree", "elevation_unit": "foot"},
        )
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(TerrainDataError):
                    KMLTerrainProvider.from_file(path, **values)


if __name__ == "__main__":
    unittest.main()
