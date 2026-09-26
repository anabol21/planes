"""Constant-AGL terrain profiles sampled along WGS84 geodesic segments."""

from __future__ import annotations

from dataclasses import dataclass
import math

from pyproj import Geod

from planner.io.dem.base import BaseDEM, TerrainDataError, validate_elevation


_WGS84 = Geod(ellps="WGS84")
DEFAULT_TERRAIN_SAMPLE_STEP_M = 25.0


@dataclass(frozen=True)
class TerrainSample:
    """One sampled point of a constant-AGL survey profile."""

    lat: float
    lon: float
    distance_from_start_m: float
    surface_elevation_m: float
    h_agl_m: float
    h_asl_m: float


@dataclass(frozen=True)
class TerrainProfile:
    """Canonical sampled terrain profile and derived diagnostics."""

    samples: tuple[TerrainSample, ...]
    horizontal_distance_m: float
    distance_3d_m: float
    total_climb_m: float
    total_descent_m: float
    surface_min_m: float
    surface_max_m: float


def build_terrain_profile(
    *,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    dem: BaseDEM,
    h_agl_m: float,
    sample_step_m: float = DEFAULT_TERRAIN_SAMPLE_STEP_M,
) -> TerrainProfile:
    """Sample surface elevation and construct a constant-AGL profile.

    Sampling uses WGS84 geodesic distance. The interval count is
    ``ceil(horizontal_distance / sample_step_m)`` and both endpoints are
    always included. ``distance_3d_m`` is diagnostic only; Grisha physics owns
    time and energy and consumes the sampled vertical profile directly.
    """
    h_agl_m = validate_elevation(h_agl_m, source="survey AGL")
    sample_step_m = validate_elevation(
        sample_step_m, source="terrain sample step"
    )
    if h_agl_m < 0:
        raise TerrainDataError("survey AGL must be non-negative")
    if sample_step_m <= 0:
        raise TerrainDataError("terrain sample step must be greater than zero")

    azimuth_deg, _, distance_m = _WGS84.inv(
        start_lon, start_lat, end_lon, end_lat
    )
    distance_m = max(0.0, float(distance_m))
    # Geodesic round-off must not create a spurious extra interval at an exact
    # multiple of the requested step.
    interval_count = max(1, math.ceil(distance_m / sample_step_m - 1e-9))

    samples: list[TerrainSample] = []
    for index in range(interval_count + 1):
        fraction = index / interval_count
        along_m = distance_m * fraction
        if index == 0:
            lon, lat = start_lon, start_lat
        elif index == interval_count:
            lon, lat = end_lon, end_lat
        else:
            lon, lat, _ = _WGS84.fwd(
                start_lon, start_lat, azimuth_deg, along_m
            )
        surface_m = validate_elevation(
            dem.h(lat, lon), source=type(dem).__name__
        )
        samples.append(
            TerrainSample(
                lat=float(lat),
                lon=float(lon),
                distance_from_start_m=along_m,
                surface_elevation_m=surface_m,
                h_agl_m=h_agl_m,
                h_asl_m=surface_m + h_agl_m,
            )
        )

    distance_3d_m = 0.0
    total_climb_m = 0.0
    total_descent_m = 0.0
    for left, right in zip(samples, samples[1:]):
        horizontal_m = right.distance_from_start_m - left.distance_from_start_m
        delta_z_m = right.h_asl_m - left.h_asl_m
        distance_3d_m += math.hypot(horizontal_m, delta_z_m)
        total_climb_m += max(delta_z_m, 0.0)
        total_descent_m += max(-delta_z_m, 0.0)

    surface_values = [sample.surface_elevation_m for sample in samples]
    return TerrainProfile(
        samples=tuple(samples),
        horizontal_distance_m=distance_m,
        distance_3d_m=distance_3d_m,
        total_climb_m=total_climb_m,
        total_descent_m=total_descent_m,
        surface_min_m=min(surface_values),
        surface_max_m=max(surface_values),
    )
