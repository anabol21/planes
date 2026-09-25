"""Deterministic terrain providers and AGL route profiling.

The module is deliberately independent of solvers, network services, and heavy
GIS libraries. Coordinates passed to providers are WGS84 longitude/latitude in
degrees; elevations and all calculated distances are metres.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, ceil, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import Iterable, Protocol, Sequence, Tuple
from xml.etree import ElementTree


EARTH_RADIUS_M = 6_371_000.0
LatLon = Tuple[float, float]


class TerrainDataError(ValueError):
    """Raised when terrain data is absent, invalid, or unsupported."""


class TerrainProvider(Protocol):
    """Elevation lookup for explicit WGS84 longitude/latitude coordinates."""

    def elevation_m(self, lon_deg: float, lat_deg: float) -> float:
        """Return finite terrain elevation in metres."""


@dataclass(frozen=True)
class ElevationPoint:
    """One deterministic WGS84 elevation sample."""

    lon_deg: float
    lat_deg: float
    elevation_m: float

    def __post_init__(self) -> None:
        _validate_lon_lat(self.lon_deg, self.lat_deg)
        _validate_finite_elevation(self.elevation_m)


@dataclass(frozen=True)
class TerrainSample:
    """One sample of a terrain-following survey altitude profile."""

    distance_m: float
    lat_deg: float
    lon_deg: float
    terrain_elevation_m: float
    required_altitude_m: float


@dataclass(frozen=True)
class TerrainProfile:
    """Sampled AGL profile and its horizontal and three-dimensional lengths."""

    samples: Tuple[TerrainSample, ...]
    horizontal_distance_m: float
    distance_3d_m: float


class FlatTerrainProvider:
    """Return one constant, finite elevation for every valid WGS84 position."""

    def __init__(self, elevation_m: float = 0.0) -> None:
        self._elevation_m = _validate_finite_elevation(elevation_m)

    def elevation_m(self, lon_deg: float, lat_deg: float) -> float:
        _validate_lon_lat(lon_deg, lat_deg)
        return self._elevation_m


class InMemoryTerrainProvider:
    """Interpolate deterministic point samples with two-neighbour IDW.

    Exact coordinate matches return their stored value. Other positions use
    inverse-distance weighting of the two nearest samples (or the sole sample
    when only one exists). The method is intentionally small and deterministic;
    it is suitable for synthetic fixtures, not a production raster model.
    """

    def __init__(self, points: Sequence[ElevationPoint]) -> None:
        if not points:
            raise TerrainDataError("terrain provider requires at least one point")
        self._points = tuple(points)

    @property
    def points(self) -> Tuple[ElevationPoint, ...]:
        return self._points

    def elevation_m(self, lon_deg: float, lat_deg: float) -> float:
        _validate_lon_lat(lon_deg, lat_deg)
        ranked = sorted(
            (
                haversine_m(lat_deg, lon_deg, point.lat_deg, point.lon_deg),
                index,
                point,
            )
            for index, point in enumerate(self._points)
        )
        if ranked[0][0] <= 1e-6:
            return ranked[0][2].elevation_m
        if len(ranked) == 1:
            return ranked[0][2].elevation_m

        first, second = ranked[:2]
        weight_first = 1.0 / first[0]
        weight_second = 1.0 / second[0]
        elevation = (
            first[2].elevation_m * weight_first
            + second[2].elevation_m * weight_second
        ) / (weight_first + weight_second)
        return _validate_finite_elevation(elevation)


class KMLTerrainProvider(InMemoryTerrainProvider):
    """Load finite ``lon,lat,elevation`` tuples from a small local KML file."""

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        crs: str,
        horizontal_unit: str,
        elevation_unit: str,
    ) -> "KMLTerrainProvider":
        if crs.strip().upper() != "EPSG:4326":
            raise TerrainDataError(
                f"unsupported terrain CRS {crs!r}; TER-001 KML requires EPSG:4326"
            )
        if horizontal_unit != "degree":
            raise TerrainDataError(
                "TER-001 KML horizontal_unit must be explicitly 'degree'"
            )
        if elevation_unit != "metre":
            raise TerrainDataError(
                "TER-001 KML elevation_unit must be explicitly 'metre'"
            )

        terrain_path = Path(path)
        try:
            root = ElementTree.parse(terrain_path).getroot()
        except (OSError, ElementTree.ParseError) as exc:
            raise TerrainDataError(
                f"cannot read terrain KML {terrain_path}: {exc}"
            ) from exc

        points = []
        for element in root.iter():
            if not element.tag.endswith("coordinates") or not element.text:
                continue
            points.extend(_parse_kml_coordinates(element.text))
        if not points:
            raise TerrainDataError(
                f"terrain KML {terrain_path} contains no finite 3D coordinates"
            )
        return cls(points)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 coordinates."""

    _validate_lon_lat(lon1, lat1)
    _validate_lon_lat(lon2, lat2)
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    hav = (
        sin(delta_phi / 2.0) ** 2
        + cos(phi1) * cos(phi2) * sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * atan2(sqrt(hav), sqrt(max(0.0, 1.0 - hav)))


def sample_segment(
    start: LatLon,
    end: LatLon,
    sample_step_m: float = 25.0,
) -> Tuple[LatLon, ...]:
    """Sample a short WGS84 segment with endpoints and no duplicate samples.

    The number of intervals is ``ceil(haversine_distance / sample_step_m)``.
    Coordinates are interpolated deterministically by fraction; every distance
    calculation remains geodesic rather than treating degrees as metres.
    """

    if not isfinite(sample_step_m) or sample_step_m <= 0.0:
        raise ValueError("sample_step_m must be finite and strictly positive")
    lat_start, lon_start = start
    lat_end, lon_end = end
    _validate_lon_lat(lon_start, lat_start)
    _validate_lon_lat(lon_end, lat_end)
    distance = haversine_m(lat_start, lon_start, lat_end, lon_end)
    if distance <= 1e-9:
        return ((lat_start, lon_start),)

    interval_count = max(1, int(ceil(distance / sample_step_m)))
    return tuple(
        (
            lat_start + (lat_end - lat_start) * index / interval_count,
            lon_start + (lon_end - lon_start) * index / interval_count,
        )
        for index in range(interval_count + 1)
    )


def build_agl_profile(
    start: LatLon,
    end: LatLon,
    provider: TerrainProvider,
    agl_m: float,
    sample_step_m: float = 25.0,
) -> TerrainProfile:
    """Build a terrain-following survey profile at constant AGL.

    Required absolute altitude is ``terrain_elevation + agl_m``. Missing or
    non-finite provider results fail closed with :class:`TerrainDataError`.
    """

    if not isfinite(agl_m) or agl_m < 0.0:
        raise ValueError("agl_m must be finite and non-negative")

    positions = sample_segment(start, end, sample_step_m)
    samples = []
    horizontal_total = 0.0
    distance_3d_total = 0.0
    previous_position = None
    previous_altitude = None

    for lat_deg, lon_deg in positions:
        elevation = _provider_elevation(provider, lon_deg, lat_deg)
        required_altitude = elevation + agl_m
        if previous_position is not None and previous_altitude is not None:
            horizontal = haversine_m(
                previous_position[0], previous_position[1], lat_deg, lon_deg
            )
            vertical = required_altitude - previous_altitude
            horizontal_total += horizontal
            distance_3d_total += sqrt(horizontal * horizontal + vertical * vertical)
        samples.append(
            TerrainSample(
                distance_m=horizontal_total,
                lat_deg=lat_deg,
                lon_deg=lon_deg,
                terrain_elevation_m=elevation,
                required_altitude_m=required_altitude,
            )
        )
        previous_position = (lat_deg, lon_deg)
        previous_altitude = required_altitude

    return TerrainProfile(
        samples=tuple(samples),
        horizontal_distance_m=horizontal_total,
        distance_3d_m=distance_3d_total,
    )


def endpoint_distance_3d(
    start: LatLon,
    end: LatLon,
    provider: TerrainProvider,
    agl_m: float,
) -> float:
    """Return transfer distance using terrain-derived endpoint altitudes only.

    This does not sample or certify intermediate transfer clearance. That policy
    remains open in TER-001.
    """

    if not isfinite(agl_m) or agl_m < 0.0:
        raise ValueError("agl_m must be finite and non-negative")
    lat_start, lon_start = start
    lat_end, lon_end = end
    start_altitude = _provider_elevation(provider, lon_start, lat_start) + agl_m
    end_altitude = _provider_elevation(provider, lon_end, lat_end) + agl_m
    horizontal = haversine_m(lat_start, lon_start, lat_end, lon_end)
    return sqrt(horizontal * horizontal + (end_altitude - start_altitude) ** 2)


def _parse_kml_coordinates(text: str) -> Iterable[ElevationPoint]:
    for token in text.split():
        values = token.split(",")
        if len(values) < 3 or not values[2].strip():
            raise TerrainDataError(
                "terrain KML coordinate must contain lon,lat,elevation"
            )
        try:
            lon_deg, lat_deg, elevation_m = map(float, values[:3])
        except ValueError as exc:
            raise TerrainDataError(
                f"invalid terrain KML coordinate {token!r}"
            ) from exc
        yield ElevationPoint(lon_deg, lat_deg, elevation_m)


def _provider_elevation(
    provider: TerrainProvider,
    lon_deg: float,
    lat_deg: float,
) -> float:
    try:
        value = provider.elevation_m(lon_deg, lat_deg)
    except TerrainDataError:
        raise
    except Exception as exc:
        raise TerrainDataError(
            f"terrain elevation unavailable at ({lon_deg}, {lat_deg}): {exc}"
        ) from exc
    return _validate_finite_elevation(value)


def _validate_finite_elevation(value: object) -> float:
    if isinstance(value, bool):
        raise TerrainDataError("terrain elevation must be a finite number")
    try:
        elevation = float(value)
    except (TypeError, ValueError) as exc:
        raise TerrainDataError("terrain elevation is missing or non-numeric") from exc
    if not isfinite(elevation):
        raise TerrainDataError("terrain elevation must be finite")
    return elevation


def _validate_lon_lat(lon_deg: float, lat_deg: float) -> None:
    if not isfinite(lon_deg) or not isfinite(lat_deg):
        raise TerrainDataError("longitude and latitude must be finite")
    if not -180.0 <= lon_deg <= 180.0:
        raise TerrainDataError("longitude must be within [-180, 180] degrees")
    if not -90.0 <= lat_deg <= 90.0:
        raise TerrainDataError("latitude must be within [-90, 90] degrees")
