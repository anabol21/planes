"""Чтение KML: препятствия с высотами."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from planner.models import Obstacle

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _parse_height(description: str | None) -> float:
    """Достаёт height=NN из description. Если нет — 0."""
    if not description:
        return 0.0
    for token in description.replace(";", " ").split():
        if token.startswith("height="):
            try:
                return float(token.split("=", 1)[1])
            except ValueError:
                return 0.0
    return 0.0


def _coords_to_polygon(coords_text: str) -> dict:
    """'lon,lat,alt lon,lat,alt ...' → GeoJSON Polygon."""
    pts: list[list[float]] = []
    for chunk in coords_text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon = float(parts[0])
        lat = float(parts[1])
        pts.append([lon, lat])

    if len(pts) < 3:
        raise ValueError("KML ring has fewer than 3 points")

    if pts[0] != pts[-1]:
        pts.append(pts[0])

    return {"type": "Polygon", "coordinates": [pts]}


def read_obstacles_kml(path: str | Path) -> list[Obstacle]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"KML not found: {path}")

    tree = etree.parse(str(path))
    root = tree.getroot()

    obstacles: list[Obstacle] = []
    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name_el = placemark.find("kml:name", KML_NS)
        desc_el = placemark.find("kml:description", KML_NS)
        coords_el = placemark.find(
            ".//kml:Polygon//kml:outerBoundaryIs//kml:LinearRing//kml:coordinates",
            KML_NS,
        )
        if coords_el is None or coords_el.text is None:
            continue

        name = (name_el.text or "").strip() if name_el is not None else ""
        desc = (desc_el.text or "").strip() if desc_el is not None else ""

        obstacles.append(
            Obstacle(
                id=name or f"obs-{len(obstacles) + 1}",
                name=name,
                height_m=_parse_height(desc),
                polygon=_coords_to_polygon(coords_el.text.strip()),
            )
        )

    return obstacles