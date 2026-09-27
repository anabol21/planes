"""Parse survey and constraint KML into polygons.

Coordinates are longitude, latitude in degrees, CRS EPSG:4326. Altitude
sentences are copied as text and are not converted into metres.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstraintPolygon:
    """One restriction polygon. ``altitudes_text`` is copied, not interpreted."""

    ring: tuple[tuple[float, float], ...]
    name: str | None
    type: str | None
    altitudes_text: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ring": [[lon, lat] for lon, lat in self.ring],
            "name": self.name,
            "type": self.type,
            "altitudes_text": self.altitudes_text,
        }


def parse_survey_polygon(text: str) -> list[ConstraintPolygon]:
    """Return every survey polygon. Each one is its own area.

    Rings are EPSG:4326. A document with no polygon is an error. Several
    polygons are kept; none of them is dropped.
    """
    polygons = _polygons(text)
    if not polygons:
        raise ValueError("survey KML has no polygon")
    return polygons


def parse_constraint_polygons(text: str | None) -> list[ConstraintPolygon]:
    """Return restriction polygons: ring, name, type, and copied altitude text.

    ``None`` and a blank string are an empty file: no polygons and no error.
    """
    if text is None or not text.strip():
        return []
    return _polygons(text)


def _polygons(text: str) -> list[ConstraintPolygon]:
    root = _root(text)
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    polygons: list[ConstraintPolygon] = []
    for placemark in _named(root, "Placemark"):
        name = _direct_text(placemark, "name")
        extended = _extended_data(placemark, parent_map)
        label = _extended_value(extended, "Name") or name
        kind = _extended_value(extended, "Type")
        altitudes = _extended_value(extended, "Altitudes")
        for polygon in _named(placemark, "Polygon"):
            if _nearest_ancestor(polygon, "Placemark", parent_map) is not placemark:
                continue
            ring = _outer_ring(polygon, parent_map)
            if ring is None:
                continue
            polygons.append(
                ConstraintPolygon(
                    ring=tuple(ring),
                    name=label,
                    type=kind,
                    altitudes_text=altitudes,
                )
            )
    return polygons


def _root(text: str) -> ET.Element:
    if not text or not str(text).strip():
        raise ValueError("KML file is empty")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("KML contains malformed XML") from exc
    if _local(root.tag).lower() != "kml":
        raise ValueError("The selected file is not a KML document")
    return root


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _named(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local(element.tag) == name]


def _direct_text(element: ET.Element, name: str) -> str | None:
    for child in list(element):
        if _local(child.tag) == name:
            return _normalized(child.text)
    return None


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _nearest_ancestor(
    element: ET.Element,
    name: str,
    parent_map: dict[ET.Element, ET.Element],
) -> ET.Element | None:
    current = parent_map.get(element)
    while current is not None:
        if _local(current.tag) == name:
            return current
        current = parent_map.get(current)
    return None


def _extended_data(
    placemark: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for element in _named(placemark, "Data"):
        if _nearest_ancestor(element, "Placemark", parent_map) is not placemark:
            continue
        key = (element.get("name") or "").strip()
        if not key:
            continue
        value_element = next(
            (
                child
                for child in _named(element, "value")
                if _nearest_ancestor(child, "Data", parent_map) is element
            ),
            None,
        )
        raw = value_element.text if value_element is not None else "".join(element.itertext())
        value = _normalized(raw)
        if value:
            fields[key] = value
    for element in _named(placemark, "SimpleData"):
        if _nearest_ancestor(element, "Placemark", parent_map) is not placemark:
            continue
        key = (element.get("name") or "").strip()
        value = _normalized("".join(element.itertext()))
        if key and value and key not in fields:
            fields[key] = value
    return fields


def _extended_value(data: dict[str, str], key: str) -> str | None:
    if key in data:
        return data[key]
    for name, value in data.items():
        if name.lower() == key.lower():
            return value
    return None


def _outer_ring(
    polygon: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> list[tuple[float, float]] | None:
    outers = [
        element
        for element in _named(polygon, "outerBoundaryIs")
        if _nearest_ancestor(element, "Polygon", parent_map) is polygon
    ]
    if not outers:
        return None
    coordinates = [
        element
        for element in _named(outers[0], "coordinates")
        if _nearest_ancestor(element, "Polygon", parent_map) is polygon
    ]
    if not coordinates:
        return None
    points = _coordinates("".join(coordinates[0].itertext()))
    if len(points) < 3:
        return None
    ring = [(point[0], point[1]) for point in points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _coordinates(text: str) -> list[tuple[float, float]]:
    normalized = _normalized(text)
    if not normalized:
        return []
    points: list[tuple[float, float]] = []
    for token in normalized.split(" "):
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("KML coordinate is outside EPSG:4326 longitude/latitude")
        points.append((lon, lat))
    return points
