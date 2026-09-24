"""KML outer rings for the solver scenario.

The browser extracts the same rings before upload. This module exists so a
runtime test can build that scenario from a short KML snippet. Full organizer
files stay out of git. Altitude sentences are copied, not interpreted.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


_INPUT = (
    Path(__file__).resolve().parents[1]
    / "model"
    / "basic_model"
    / "gibrid-optimizer"
    / "data"
    / "input.json"
)

DEFAULT_PROFILE_SOURCE = (
    "src/planes/model/basic_model/gibrid-optimizer/data/input.json"
)
DEFAULT_PROFILE_NOTE = (
    "gsd_cm_per_px, camera, survey overlaps and strip direction, "
    "power_coeffs, mass_kg, v_vertical_ms, and max_wind_ms are the "
    "default profile from src/planes/model/basic_model/gibrid-optimizer/data/input.json, "
    "not user input."
)


def solver_criterion(objective: str) -> str:
    if objective == "min_time":
        return "min_time"
    if objective == "min_total_flight_time":
        return "min_flight_hours"
    raise ValueError(f"unsupported criterion: {objective}")


def extract_polygons(text: str) -> list[dict[str, Any]]:
    root = _root(text)
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    polygons: list[dict[str, Any]] = []
    for placemark in _named(root, "Placemark"):
        name = _direct_text(placemark, "name")
        extended = _extended_data(placemark, parent_map)
        for polygon in _named(placemark, "Polygon"):
            if _nearest_ancestor(polygon, "Placemark", parent_map) is not placemark:
                continue
            ring = _outer_ring(polygon, parent_map)
            if ring is None:
                continue
            polygons.append(
                {
                    "name": name,
                    "ring": ring["ring"],
                    "height_m": ring["height_m"],
                    "extended_data": extended,
                }
            )
    return polygons


def build_input_scenario(
    *,
    survey_kml: str,
    launch_lat: float,
    launch_lon: float,
    uav_model: str,
    uav_count: int,
    v_air_ms: float,
    battery_wh: float,
    max_flight_time_s: float,
    wind_speed_ms: float,
    wind_direction_deg: float,
    restriction_kml: str | None = None,
    obstacle_kml_documents: list[str] | None = None,
    objective: str = "min_time",
    survey_type: str | None = None,
) -> dict[str, Any]:
    """Assemble Grisha's scenario fields plus rings the solver does not read yet."""
    if wind_direction_deg < 0 or wind_direction_deg > 360:
        raise ValueError("wind direction must be from 0 to 360 degrees")
    area = _survey_ring(survey_kml)
    bounds = _ring_bounds(area)
    if bounds is None:
        raise ValueError("survey KML has no polygon")
    defaults = _default_profile()
    zones = []
    if restriction_kml:
        for polygon in extract_polygons(restriction_kml):
            zones.append(
                {
                    "ring": polygon["ring"],
                    "name": _extended_value(polygon["extended_data"], "Name") or polygon["name"],
                    "type": _extended_value(polygon["extended_data"], "Type"),
                    "altitudes_text": _extended_value(polygon["extended_data"], "Altitudes"),
                }
            )
    obstacles = []
    for document in obstacle_kml_documents or []:
        for polygon in extract_polygons(document):
            if not _ring_intersects_bounds(polygon["ring"], bounds):
                continue
            obstacles.append(
                {
                    "ring": polygon["ring"],
                    "height_m": polygon["height_m"],
                    "kind": polygon["name"],
                }
            )
    scenario: dict[str, Any] = {
        "crs": "EPSG:4326",
        "criterion": solver_criterion(objective),
        "gsd_cm_per_px": defaults["gsd_cm_per_px"],
        "area": area,
        "takeoff": {"lat": launch_lat, "lon": launch_lon},
        "uav": {
            "model": uav_model,
            "count": uav_count,
            "mass_kg": defaults["mass_kg"],
            "max_flight_time_s": max_flight_time_s,
            "battery_wh": battery_wh,
            "v_air_ms": v_air_ms,
            "v_vertical_ms": defaults["v_vertical_ms"],
            "max_wind_ms": defaults["max_wind_ms"],
        },
        "camera": defaults["camera"],
        "survey": defaults["survey"],
        "wind": {
            "speed_ms": wind_speed_ms,
            "direction_deg": 0.0 if wind_direction_deg == 360 else wind_direction_deg,
        },
        "power_coeffs": defaults["power_coeffs"],
        "zone_constraints": zones,
        "obstacles": obstacles,
        "default_profile": {
            "note": DEFAULT_PROFILE_NOTE,
            "source": DEFAULT_PROFILE_SOURCE,
        },
    }
    if survey_type is not None:
        scenario["survey_type"] = survey_type
    return scenario


def _default_profile() -> dict[str, Any]:
    payload = json.loads(_INPUT.read_text(encoding="utf-8"))
    uav = payload["uav"]
    return {
        "gsd_cm_per_px": payload["gsd_cm_per_px"],
        "camera": payload["camera"],
        "survey": payload["survey"],
        "power_coeffs": payload["power_coeffs"],
        "mass_kg": uav["mass_kg"],
        "v_vertical_ms": uav["v_vertical_ms"],
        "max_wind_ms": uav["max_wind_ms"],
    }


def _survey_ring(text: str) -> list[list[float]]:
    polygons = extract_polygons(text)
    if not polygons:
        raise ValueError("survey KML has no polygon")
    if len(polygons) > 1:
        listed = "; ".join(_polygon_label(polygon, index) for index, polygon in enumerate(polygons))
        raise ValueError(f"survey KML has multiple polygons: {listed}")
    return polygons[0]["ring"]


def _polygon_label(polygon: dict[str, Any], index: int) -> str:
    name = (polygon.get("name") or "").strip() or f"polygon {index + 1}"
    ring = polygon["ring"]
    if not ring:
        return name
    return f"{name} ({ring[0][0]}, {ring[0][1]})"


def _root(text: str) -> ET.Element:
    if not text or not text.strip():
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
        value = _normalized(value_element.text if value_element is not None else "".join(element.itertext()))
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
) -> dict[str, Any] | None:
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
    altitudes = [point[2] for point in points if point[2] is not None]
    return {
        "ring": [[point[0], point[1]] for point in points],
        "height_m": max(altitudes) if altitudes else None,
    }


def _coordinates(text: str) -> list[tuple[float, float, float | None]]:
    normalized = _normalized(text)
    if not normalized:
        return []
    points: list[tuple[float, float, float | None]] = []
    for token in normalized.split(" "):
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        alt: float | None = None
        if len(parts) >= 3 and parts[2].strip():
            try:
                alt = float(parts[2])
            except ValueError:
                alt = None
        points.append((lon, lat, alt))
    return points


def _ring_bounds(ring: list[list[float]]) -> dict[str, float] | None:
    if not ring:
        return None
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return {
        "west": min(lons),
        "south": min(lats),
        "east": max(lons),
        "north": max(lats),
    }


def _ring_intersects_bounds(ring: list[list[float]], bounds: dict[str, float]) -> bool:
    points = [point for point in ring if len(point) >= 2]
    if len(points) < 3:
        return False
    if any(_inside_bounds(point[0], point[1], bounds) for point in points):
        return True
    corners = [
        (bounds["west"], bounds["south"]),
        (bounds["east"], bounds["south"]),
        (bounds["east"], bounds["north"]),
        (bounds["west"], bounds["north"]),
    ]
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        for corner_index, edge_start in enumerate(corners):
            edge_end = corners[(corner_index + 1) % len(corners)]
            if _segments_intersect(
                start[0],
                start[1],
                end[0],
                end[1],
                edge_start[0],
                edge_start[1],
                edge_end[0],
                edge_end[1],
            ):
                return True
    return _point_in_ring(bounds["west"], bounds["south"], points)


def _inside_bounds(lon: float, lat: float, bounds: dict[str, float]) -> bool:
    return bounds["west"] <= lon <= bounds["east"] and bounds["south"] <= lat <= bounds["north"]


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def _on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    return min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)


def _segments_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    d1 = _cross(cx - ax, cy - ay, bx - ax, by - ay)
    d2 = _cross(dx - ax, dy - ay, bx - ax, by - ay)
    d3 = _cross(ax - cx, ay - cy, dx - cx, dy - cy)
    d4 = _cross(bx - cx, by - cy, dx - cx, dy - cy)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    if d1 == 0 and _on_segment(cx, cy, ax, ay, bx, by):
        return True
    if d2 == 0 and _on_segment(dx, dy, ax, ay, bx, by):
        return True
    if d3 == 0 and _on_segment(ax, ay, cx, cy, dx, dy):
        return True
    if d4 == 0 and _on_segment(bx, by, cx, cy, dx, dy):
        return True
    return False


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = len(ring) - 1
    for index, point in enumerate(ring):
        xi, yi = point[0], point[1]
        xj, yj = ring[previous][0], ring[previous][1]
        if (yi > lat) != (yj > lat):
            x_cross = ((xj - xi) * (lat - yi)) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        previous = index
    return inside
