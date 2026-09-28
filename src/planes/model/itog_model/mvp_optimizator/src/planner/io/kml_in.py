"""Чтение KML: препятствия и запретные зоны.

Поддерживаются:
  - Polygon (footprint);
  - Point (точечное препятствие → квадрат 10×10 м);
  - MultiGeometry (разворачивается в несколько объектов).

Высота извлекается из <description> в свободной форме:
  height=50, Height: 50, высота 50, h=50, 50 m.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from lxml import etree

from planner.models import NoFlyZone, Obstacle


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

POINT_OBSTACLE_RADIUS_M = 5.0
_M_PER_DEG_LAT = 111_320.0


# ============================================================
# Парсинг высоты
# ============================================================

_HEIGHT_RE = re.compile(
    r"""
    (?:
        height | высота | h
    )
    \s*
    (?:[=:]|\s)
    \s*
    (?P<val>\d+(?:[.,]\d+)?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_HEIGHT_M_RE = re.compile(
    r"(?P<val>\d+(?:[.,]\d+)?)\s*(?:m\b|м\b|meters?|метров?|м\.)",
    re.IGNORECASE,
)


def _parse_height(description: str | None) -> float:
    """Извлекает высоту из свободного текста описания."""
    if not description:
        return 0.0

    text = str(description).replace(",", ".")

    m = _HEIGHT_RE.search(text)
    if m:
        try:
            return float(m.group("val"))
        except ValueError:
            pass

    m = _HEIGHT_M_RE.search(text)
    if m:
        try:
            return float(m.group("val"))
        except ValueError:
            pass

    return 0.0


# ============================================================
# Парсинг координат
# ============================================================

def _parse_coords_text(
    coords_text: str,
) -> list[tuple[float, float, float]]:
    """'lon,lat,alt lon,lat,alt ...' → [(lon, lat, alt), ...]."""
    points: list[tuple[float, float, float]] = []
    if not coords_text:
        return points

    for chunk in coords_text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else 0.0
        except ValueError:
            continue
        points.append((lon, lat, alt))

    return points


def _close_ring(pts: list[list[float]]) -> list[list[float]]:
    if not pts:
        return pts
    if pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    return pts


def _coords_to_polygon(coords_text: str) -> dict | None:
    """Строка координат → GeoJSON Polygon. None, если точек < 3."""
    raw = _parse_coords_text(coords_text)
    if len(raw) < 3:
        return None

    pts: list[list[float]] = [[lon, lat] for lon, lat, _ in raw]
    pts = _close_ring(pts)
    return {"type": "Polygon", "coordinates": [pts]}


def _point_to_polygon(
    coords_text: str,
    radius_m: float = POINT_OBSTACLE_RADIUS_M,
) -> dict | None:
    """Точка → квадрат вокруг неё."""
    raw = _parse_coords_text(coords_text)
    if not raw:
        return None

    lon, lat, _ = raw[0]

    dlat = radius_m / _M_PER_DEG_LAT
    dlon = radius_m / (
        _M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6)
    )

    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


# ============================================================
# Разбор Placemark
# ============================================================

def _placemark_geometries(placemark) -> list[dict]:
    """Polygon / Point / MultiGeometry → список GeoJSON-полигонов."""
    geoms: list[dict] = []

    for poly in placemark.findall(".//kml:Polygon", KML_NS):
        coords_el = poly.find(
            ".//kml:outerBoundaryIs//kml:LinearRing//kml:coordinates",
            KML_NS,
        )
        if coords_el is None or coords_el.text is None:
            continue
        geom = _coords_to_polygon(coords_el.text.strip())
        if geom is not None:
            geoms.append(geom)

    for point in placemark.findall(".//kml:Point", KML_NS):
        coords_el = point.find("kml:coordinates", KML_NS)
        if coords_el is None or coords_el.text is None:
            continue
        geom = _point_to_polygon(coords_el.text.strip())
        if geom is not None:
            geoms.append(geom)

    return geoms


# ============================================================
# Препятствия
# ============================================================

def read_obstacles_kml(path: str | Path) -> list[Obstacle]:
    """Читает KML с препятствиями."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"KML not found: {path}")

    tree = etree.parse(str(path))
    root = tree.getroot()

    obstacles: list[Obstacle] = []

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name_el = placemark.find("kml:name", KML_NS)
        desc_el = placemark.find("kml:description", KML_NS)

        name = ""
        if name_el is not None and name_el.text:
            name = name_el.text.strip()

        desc = ""
        if desc_el is not None and desc_el.text:
            desc = desc_el.text.strip()

        height = _parse_height(desc)

        geoms = _placemark_geometries(placemark)
        if not geoms:
            continue

        base_id = name or f"obs-{len(obstacles) + 1}"

        for k, geom in enumerate(geoms):
            obs_id = base_id if len(geoms) == 1 else f"{base_id}-{k + 1}"

            obstacles.append(
                Obstacle(
                    id=obs_id,
                    name=name,
                    height_m=height,
                    polygon=geom,
                )
            )

    return obstacles


# ============================================================
# Запретные зоны
# ============================================================

def read_no_fly_zones_kml(path: str | Path) -> list[NoFlyZone]:
    """Читает KML с запретными зонами.

    Отличия от obstacles:
      - нет height_m (запрет абсолютный);
      - точка → квадрат 5×5 м (та же логика);
      - возвращает пустой список, если файла нет.

    KML-файл опционален: если его нет — запреток нет.
    """
    path = Path(path)
    if not path.exists():
        return []

    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError:
        return []

    root = tree.getroot()

    zones: list[NoFlyZone] = []

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name_el = placemark.find("kml:name", KML_NS)
        name = ""
        if name_el is not None and name_el.text:
            name = name_el.text.strip()

        geoms = _placemark_geometries(placemark)
        if not geoms:
            continue

        base_id = name or f"nfz-{len(zones) + 1}"

        for k, geom in enumerate(geoms):
            nfz_id = base_id if len(geoms) == 1 else f"{base_id}-{k + 1}"

            zones.append(
                NoFlyZone(
                    id=nfz_id,
                    name=name,
                    polygon=geom,
                )
            )

    return zones