"""Canonical interface and validation helpers for local elevation sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
import math


class TerrainDataError(ValueError):
    """Raised when requested terrain cannot provide a trustworthy elevation."""


def validate_elevation(value: float | None, *, source: str) -> float:
    """Return a finite elevation in metres or fail closed."""
    if value is None:
        raise TerrainDataError(f"{source} returned a missing elevation")
    try:
        elevation = float(value)
    except (TypeError, ValueError) as exc:
        raise TerrainDataError(f"{source} returned an invalid elevation") from exc
    if not math.isfinite(elevation):
        raise TerrainDataError(f"{source} returned a non-finite elevation")
    return elevation


class BaseDEM(ABC):
    """Local, deterministic surface-elevation provider.

    Coordinates are WGS84 latitude/longitude degrees and the result is metres
    in the source raster's declared vertical datum.
    """

    @abstractmethod
    def h(self, lat: float, lon: float) -> float:
        """Return finite surface elevation in metres for a WGS84 point."""

    def elevation_m(self, lon_deg: float, lat_deg: float) -> float:
        """TER-001-compatible spelling; canonical implementation remains ``h``."""
        return validate_elevation(
            self.h(lat_deg, lon_deg), source=type(self).__name__
        )

    @abstractmethod
    def is_empty(self) -> bool:
        """True, если DEM не задан (плоская земля)."""

    def h_max(self) -> float:
        raise NotImplementedError

    def h_min(self) -> float:
        raise NotImplementedError
