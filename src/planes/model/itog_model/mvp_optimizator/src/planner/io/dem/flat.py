"""Explicit constant-elevation provider used for compatibility and tests."""

from __future__ import annotations

from planner.io.dem.base import BaseDEM, validate_elevation


class FlatDEM(BaseDEM):
    """Return one finite surface elevation everywhere."""

    def __init__(self, elevation_m: float = 0.0):
        self._elevation_m = validate_elevation(
            elevation_m, source="FlatDEM configuration"
        )

    def h(self, lat: float, lon: float) -> float:
        return self._elevation_m

    def is_empty(self) -> bool:
        return False

    def h_max(self) -> float:
        return self._elevation_m

    def h_min(self) -> float:
        return self._elevation_m
