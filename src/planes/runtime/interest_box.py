"""Interest rectangle for the listener shell.

The rectangle is the axis-aligned bounds, in EPSG:4326 degrees, of survey-ring
vertices and aerodrome points. Constraint vertices, routes, and other
placemarks are not part of that pool. No padding is added.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from planes.integration.kml.constraints import ConstraintPoint, ConstraintPolygon


_PolygonT = TypeVar("_PolygonT", bound=ConstraintPolygon)
_PointT = TypeVar("_PointT", bound=ConstraintPoint)


@dataclass(frozen=True)
class InterestRectangle:
    """Closed axis-aligned box. West/east are longitude, south/north latitude."""

    west: float
    south: float
    east: float
    north: float

    @property
    def crs(self) -> str:
        return "EPSG:4326"


def interest_rectangle(
    survey_rings: Sequence[Sequence[tuple[float, float]]],
    aerodromes_lon_lat: Sequence[tuple[float, float]],
) -> InterestRectangle:
    """Left = min lon, right = max lon, bottom = min lat, top = max lat."""
    points: list[tuple[float, float]] = []
    for ring in survey_rings:
        points.extend((float(lon), float(lat)) for lon, lat in ring)
    points.extend((float(lon), float(lat)) for lon, lat in aerodromes_lon_lat)
    if not points:
        raise ValueError("interest rectangle has no survey or aerodrome coordinates")
    west = min(lon for lon, _lat in points)
    east = max(lon for lon, _lat in points)
    south = min(lat for _lon, lat in points)
    north = max(lat for _lon, lat in points)
    if not west < east or not south < north:
        raise ValueError("interest rectangle is degenerate; padding is not added")
    return InterestRectangle(west=west, south=south, east=east, north=north)


def rectangle_geometry(rect: InterestRectangle) -> dict[str, Any]:
    """GeoJSON polygon whose bbox is exactly ``rect``. CRS is EPSG:4326."""
    ring = [
        [rect.west, rect.south],
        [rect.east, rect.south],
        [rect.east, rect.north],
        [rect.west, rect.north],
        [rect.west, rect.south],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def point_in_rectangle(lon: float, lat: float, rect: InterestRectangle) -> bool:
    """Closed rectangle: a point on the boundary stays inside."""
    return rect.west <= lon <= rect.east and rect.south <= lat <= rect.north


def ring_intersects_rectangle(
    ring: Sequence[tuple[float, float]],
    rect: InterestRectangle,
) -> bool:
    """True when the ring meets the box, including a polygon that covers it."""
    if len(ring) < 3:
        return False
    from shapely.geometry import Polygon, box

    try:
        polygon = Polygon([(float(lon), float(lat)) for lon, lat in ring])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            return False
        return bool(polygon.intersects(box(rect.west, rect.south, rect.east, rect.north)))
    except (TypeError, ValueError):
        return False


def clip_constraint_polygons(
    polygons: Sequence[_PolygonT],
    rect: InterestRectangle,
) -> list[_PolygonT]:
    """Keep a constraint only when its ring intersects the rectangle."""
    return [polygon for polygon in polygons if ring_intersects_rectangle(polygon.ring, rect)]


def clip_constraint_points(
    points: Sequence[_PointT],
    rect: InterestRectangle,
) -> list[_PointT]:
    """Drop a point that lies outside the rectangle."""
    return [point for point in points if point_in_rectangle(point.lon, point.lat, rect)]
