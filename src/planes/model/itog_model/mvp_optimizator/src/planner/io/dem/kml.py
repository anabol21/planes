"""Strict local KML surface provider with deterministic interpolation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from lxml import etree

from planner.io.dem.base import BaseDEM, TerrainDataError, validate_elevation

try:
    from scipy.interpolate import LinearNDInterpolator
except ImportError:  # pragma: no cover
    LinearNDInterpolator = None


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


class KMLDem(BaseDEM):
    """Finite WGS84 KML point elevations with linear/nearest interpolation."""

    def __init__(self, points: list[tuple[float, float, float]]):
        if not points:
            raise TerrainDataError("KML terrain contains no elevation points")
        self.points = [
            (
                validate_elevation(lat, source="KML latitude"),
                validate_elevation(lon, source="KML longitude"),
                validate_elevation(alt, source="KML elevation"),
            )
            for lat, lon, alt in points
        ]
        self._interp = None
        self._build()

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        crs: str,
        horizontal_unit: str,
        elevation_unit: str,
    ) -> "KMLDem":
        """Parse point elevations after validating explicit CRS and units."""
        if crs.strip().upper() != "EPSG:4326":
            raise TerrainDataError("KML terrain CRS must be EPSG:4326")
        if horizontal_unit != "degree":
            raise TerrainDataError("KML terrain horizontal_unit must be degree")
        if elevation_unit != "metre":
            raise TerrainDataError("KML terrain elevation_unit must be metre")

        source = Path(path)
        if not source.is_file():
            raise TerrainDataError(f"KML terrain file not found: {source}")
        try:
            tree = etree.parse(str(source))
        except (etree.XMLSyntaxError, OSError) as exc:
            raise TerrainDataError(f"Invalid KML terrain file: {source}") from exc

        points: list[tuple[float, float, float]] = []
        for coords_el in tree.getroot().findall(
            ".//kml:Point//kml:coordinates", KML_NS
        ):
            if not coords_el.text:
                continue
            for chunk in coords_el.text.split():
                parts = chunk.split(",")
                if len(parts) < 3 or not parts[2].strip():
                    raise TerrainDataError(
                        "KML terrain point is missing an elevation"
                    )
                try:
                    lon, lat, altitude = map(float, parts[:3])
                except ValueError as exc:
                    raise TerrainDataError(
                        "KML terrain point contains invalid coordinates"
                    ) from exc
                points.append((lat, lon, altitude))
        return cls(points)

    def _build(self) -> None:
        if len(self.points) < 3 or LinearNDInterpolator is None:
            return
        coordinates = np.array(
            [(point[0], point[1]) for point in self.points], dtype=float
        )
        elevations = np.array([point[2] for point in self.points], dtype=float)
        try:
            self._interp = LinearNDInterpolator(
                coordinates, elevations, fill_value=np.nan
            )
        except Exception:
            self._interp = None

    def h(self, lat: float, lon: float) -> float:
        lat = validate_elevation(lat, source="query latitude")
        lon = validate_elevation(lon, source="query longitude")
        if self._interp is not None:
            try:
                value = float(self._interp(lat, lon))
            except Exception:
                value = float("nan")
            if np.isfinite(value):
                return value
        return self._nearest(lat, lon)

    def _nearest(self, lat: float, lon: float) -> float:
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
