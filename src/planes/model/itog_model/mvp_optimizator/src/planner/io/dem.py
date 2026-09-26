"""Загрузка DEM из KML: точки высот + интерполяция ближайшей."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


@dataclass
class DEM:
    """Простой DEM: набор точек (lat, lon, alt) + метод h(lat, lon)."""

    points: list[tuple[float, float, float]] = field(default_factory=list)

    def h(self, lat: float, lon: float) -> float:
        """Высота в точке — по ближайшей из известных. Если DEM пуст — 0."""
        if not self.points:
            return 0.0
        best = min(
            self.points,
            key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2,
        )
        return best[2]

    def h_max(self) -> float:
        if not self.points:
            return 0.0
        return max(p[2] for p in self.points)

    def h_min(self) -> float:
        if not self.points:
            return 0.0
        return min(p[2] for p in self.points)

    def is_empty(self) -> bool:
        return len(self.points) == 0


def load_dem(path: str | Path | None) -> DEM:
    """
    Читает DEM из KML. Поддерживает <Placemark><Point><coordinates>lon,lat,alt</coordinates>.

    Если path = None или файл пустой / битый — возвращает пустой DEM.
    """
    if path is None:
        return DEM()

    path = Path(path)
    if not path.exists():
        return DEM()

    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError:
        return DEM()

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

    return DEM(points=points)


def compute_h_asl(
    lat: float,
    lon: float,
    h_agl_target_m: float,
    dem: DEM | None,
) -> tuple[float, float]:
    """
    Возвращает (h_agl_actual, h_asl).
    h_asl = dem(lat, lon) + h_agl_target.
    h_agl_actual = h_agl_target (допущение MVP).
    """
    if dem is None:
        return h_agl_target_m, h_agl_target_m
    dem_h = dem.h(lat, lon)
    return h_agl_target_m, dem_h + h_agl_target_m