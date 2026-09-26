"""TER-001 semantics in the canonical Grisha terrain profile."""

import math

import pytest
from pyproj import Geod

from planner.io.dem import (
    BaseDEM,
    FlatDEM,
    InMemoryDEM,
    TerrainDataError,
    build_terrain_profile,
)


GEOD = Geod(ellps="WGS84")


class SequenceDEM(BaseDEM):
    """Return a deterministic sequence for consecutive profile samples."""

    def __init__(self, values):
        self.values = iter(values)

    def h(self, lat, lon):
        return next(self.values)

    def is_empty(self):
        return False


def endpoint(distance_m=100.0):
    lon, lat, _ = GEOD.fwd(37.62, 55.75, 90.0, distance_m)
    return lat, lon


def profile(provider, *, distance_m=100.0, step_m=50.0, agl_m=150.0):
    end_lat, end_lon = endpoint(distance_m)
    return build_terrain_profile(
        start_lat=55.75,
        start_lon=37.62,
        end_lat=end_lat,
        end_lon=end_lon,
        dem=provider,
        h_agl_m=agl_m,
        sample_step_m=step_m,
    )


def test_flat_profile_constant_agl_and_no_vertical_distance():
    result = profile(FlatDEM(100.0), step_m=25.0)
    assert all(sample.h_asl_m == pytest.approx(250.0) for sample in result.samples)
    assert all(sample.h_agl_m == pytest.approx(150.0) for sample in result.samples)
    assert result.distance_3d_m == pytest.approx(result.horizontal_distance_m)
    assert result.total_climb_m == 0.0
    assert result.total_descent_m == 0.0


def test_rising_terrain_maps_100_140_180_to_250_290_330():
    result = profile(SequenceDEM([100.0, 140.0, 180.0]))
    assert [sample.h_asl_m for sample in result.samples] == pytest.approx(
        [250.0, 290.0, 330.0]
    )
    assert result.total_climb_m == pytest.approx(80.0)
    assert result.total_descent_m == 0.0


def test_falling_terrain_keeps_constant_agl():
    result = profile(SequenceDEM([180.0, 140.0, 100.0]))
    assert [sample.h_asl_m for sample in result.samples] == pytest.approx(
        [330.0, 290.0, 250.0]
    )
    assert {sample.h_agl_m for sample in result.samples} == {150.0}
    assert result.total_descent_m == pytest.approx(80.0)


def test_hill_distance_exceeds_horizontal_distance():
    result = profile(SequenceDEM([100.0, 180.0, 100.0]))
    assert result.total_climb_m == pytest.approx(80.0)
    assert result.total_descent_m == pytest.approx(80.0)
    assert result.distance_3d_m > result.horizontal_distance_m


def test_default_sampling_is_about_25_m_and_includes_endpoints():
    end_lat, end_lon = endpoint(101.0)
    result = build_terrain_profile(
        start_lat=55.75,
        start_lon=37.62,
        end_lat=end_lat,
        end_lon=end_lon,
        dem=FlatDEM(),
        h_agl_m=100.0,
    )
    assert len(result.samples) == 6  # ceil(101/25) intervals + start
    assert result.samples[0].distance_from_start_m == 0.0
    assert result.samples[-1].distance_from_start_m == pytest.approx(101.0)
    assert (len(result.samples) - 1) < result.horizontal_distance_m / 10.0


@pytest.mark.parametrize("step", [0.0, -1.0, math.nan, math.inf])
def test_invalid_sample_step_fails_closed(step):
    with pytest.raises(TerrainDataError):
        profile(FlatDEM(), step_m=step)


@pytest.mark.parametrize("elevation", [None, math.nan, math.inf, -math.inf])
def test_missing_or_non_finite_elevation_fails_closed(elevation):
    with pytest.raises(TerrainDataError):
        profile(SequenceDEM([elevation, elevation, elevation]))


def test_in_memory_provider_is_deterministic():
    provider = InMemoryDEM([(55.75, 37.62, 120.0), (55.76, 37.63, 160.0)])
    assert provider.h(55.7501, 37.6201) == 120.0
    assert provider.elevation_m(37.6299, 55.7599) == 160.0
