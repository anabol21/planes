"""DEM из KML: точки высот + гладкая интерполяция (LinearND)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from lxml import etree

from planner.io.dem.base import BaseDEM

try:
    from scipy.interpolate import LinearNDInterpolator
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


class KMLDem(BaseDEM):
    """DEM из точек KML. Гладкая линейная интерполяция."""

    def __init__(self, points: list[tuple[float, float, float]] | None = None):
        self.points = points or []
        self._interp = None
        self._fallback = 0.0
        self._build()

    @classmethod
    def from_file(cls, path: str | Path) -> "KMLDem":
        path = Path(path)
        if not path.exists():
            return cls([])

        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError:
            return cls([])

        root = tree.getroot()
        points: list[tuple[float, float, float]] = []

        for placemark in root.findall(".//kml:Placemark", KML_NS):
            coords_el = placemark.find(".//kml:Point//kml:coordinates", KML_NS)
            if coords_el is None or coords_el.text is None:
                continue
            for chunk in coords_el.text.split():
                parts = chunk.split(",")
                if len(parts) < 3:
                    continue
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    alt = float(parts[2])
                except ValueError:
                    continue
                points.append((lat, lon, alt))

        return cls(points)

    def _build(self) -> None:
        if len(self.points) < 3 or not _HAS_SCIPY:
            self._interp = None
            self._fallback = (
                float(np.mean([p[2] for p in self.points]))
                if self.points else 0.0
            )
            return

        lats = np.array([p[0] for p in self.points], dtype=float)
        lons = np.array([p[1] for p in self.points], dtype=float)
        alts = np.array([p[2] for p in self.points], dtype=float)

        try:
            self._interp = LinearNDInterpolator(
                np.column_stack([lats, lons]),
                alts,
                fill_value=np.nan,
            )
            self._fallback = float(np.mean(alts))
        except Exception:
            self._interp = None
            self._fallback = float(np.mean(alts))

    def h(self, lat: float, lon: float) -> float:
        if not self.points:
            return 0.0
        if self._interp is None:
            return self._nearest(lat, lon)
        try:
            val = float(self._interp(lat, lon))
        except Exception:
            return self._nearest(lat, lon)
        if np.isnan(val):
            return self._nearest(lat, lon)
        return val

    def _nearest(self, lat: float, lon: float) -> float:
        best = min(
            self.points,
            key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2,
        )
        return best[2]

    def is_empty(self) -> bool:
        return len(self.points) == 0

    def h_max(self) -> float:
        return max((p[2] for p in self.points), default=0.0)

    def h_min(self) -> float:
        return min((p[2] for p in self.points), default=0.0)