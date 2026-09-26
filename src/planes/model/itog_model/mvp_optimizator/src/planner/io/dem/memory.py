"""Small deterministic in-memory surface provider for tests and fixtures."""

from __future__ import annotations

from collections.abc import Iterable

from planner.io.dem.base import BaseDEM, TerrainDataError, validate_elevation


class InMemoryDEM(BaseDEM):
    """Nearest-sample provider over finite ``(lat, lon, elevation_m)`` tuples.

    Nearest-neighbour lookup is deliberately simple and deterministic. It is a
    test/synthetic provider, not a replacement for raster interpolation.
    """

    def __init__(self, samples: Iterable[tuple[float, float, float]]):
        self.points: tuple[tuple[float, float, float], ...] = tuple(
            (
                validate_elevation(lat, source="InMemoryDEM latitude"),
                validate_elevation(lon, source="InMemoryDEM longitude"),
                validate_elevation(elevation, source="InMemoryDEM elevation"),
            )
            for lat, lon, elevation in samples
        )
        if not self.points:
            raise TerrainDataError("InMemoryDEM requires at least one sample")

    def h(self, lat: float, lon: float) -> float:
        lat = validate_elevation(lat, source="query latitude")
        lon = validate_elevation(lon, source="query longitude")
        return min(
            self.points,
            key=lambda point: (point[0] - lat) ** 2 + (point[1] - lon) ** 2,
        )[2]

    def is_empty(self) -> bool:
        return False

    def h_max(self) -> float:
        return max(point[2] for point in self.points)

    def h_min(self) -> float:
        return min(point[2] for point in self.points)
