"""Acquire one cached COP30 GeoTIFF for a survey-area bounding box.

HTTP belongs here, outside the pure optimizer. Once this function returns, the
model consumes the local file and runs fully offline.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


COP30_DATASET = "COP30"
_ENDPOINT = "https://portal.opentopography.org/API/globaldem"


class TerrainAcquisitionError(RuntimeError):
    """Sanitized acquisition/cache validation failure."""


@dataclass(frozen=True)
class SurveyBounds:
    """WGS84 survey bounds in degrees."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Survey bounds must be finite")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("Survey longitude bounds are invalid")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("Survey latitude bounds are invalid")

    def normalized(self) -> tuple[str, str, str, str]:
        return (
            f"{self.west:.8f}",
            f"{self.south:.8f}",
            f"{self.east:.8f}",
            f"{self.north:.8f}",
        )


def _iter_geometry_points(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        polygons = coordinates
    else:
        raise ValueError("Survey geometry must be Polygon or MultiPolygon")
    if not isinstance(polygons, list):
        raise ValueError("Survey geometry has invalid coordinates")
    for polygon in polygons:
        if not isinstance(polygon, list):
            raise ValueError("Survey polygon has invalid rings")
        for ring in polygon:
            if not isinstance(ring, list):
                raise ValueError("Survey polygon has an invalid ring")
            for position in ring:
                if not isinstance(position, list) or len(position) < 2:
                    raise ValueError("Survey polygon has an invalid position")
                lon, lat = float(position[0]), float(position[1])
                if not math.isfinite(lon) or not math.isfinite(lat):
                    raise ValueError("Survey polygon position must be finite")
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("Survey polygon position is outside WGS84")
                yield lon, lat


def bbox_from_geojson(
    source: str | Path | dict[str, Any],
    *,
    crs: str,
    padding_m: float = 0.0,
) -> SurveyBounds:
    """Return the union bbox of survey Polygon/MultiPolygon features.

    ``padding_m`` is optional interpolation-boundary padding and defaults to
    zero. It is applied geodesically in the four cardinal directions.
    """
    if crs.strip().upper() != "EPSG:4326":
        raise ValueError("Survey GeoJSON CRS must be explicitly EPSG:4326")
    if not math.isfinite(padding_m) or padding_m < 0:
        raise ValueError("padding_m must be finite and non-negative")
    if isinstance(source, (str, Path)):
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Could not read survey GeoJSON") from exc
    else:
        data = source

    data_type = data.get("type")
    if data_type == "FeatureCollection":
        geometries = [
            feature.get("geometry") for feature in data.get("features", [])
        ]
    elif data_type == "Feature":
        geometries = [data.get("geometry")]
    else:
        geometries = [data]
    points = [
        point
        for geometry in geometries
        if isinstance(geometry, dict)
        for point in _iter_geometry_points(geometry)
    ]
    if not points:
        raise ValueError("Survey GeoJSON contains no polygon coordinates")
    west = min(point[0] for point in points)
    east = max(point[0] for point in points)
    south = min(point[1] for point in points)
    north = max(point[1] for point in points)

    if padding_m:
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        center_lon = (west + east) / 2.0
        center_lat = (south + north) / 2.0
        padded_west, _, _ = geod.fwd(west, center_lat, 270.0, padding_m)
        padded_east, _, _ = geod.fwd(east, center_lat, 90.0, padding_m)
        _, padded_south, _ = geod.fwd(center_lon, south, 180.0, padding_m)
        _, padded_north, _ = geod.fwd(center_lon, north, 0.0, padding_m)
        west, east = padded_west, padded_east
        south, north = padded_south, padded_north
    return SurveyBounds(west=west, south=south, east=east, north=north)


def _cache_directory(override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    configured = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "planes" / "terrain"


def _cache_path(bounds: SurveyBounds, cache_dir: Path) -> Path:
    material = "|".join((COP30_DATASET, *bounds.normalized()))
    digest = hashlib.sha256(material.encode("ascii")).hexdigest()[:24]
    return cache_dir / f"COP30_{digest}.tif"


def _validate_geotiff(path: Path, expected: SurveyBounds) -> None:
    try:
        with path.open("rb") as stream:
            signature = stream.read(4)
    except OSError as exc:
        raise TerrainAcquisitionError("Could not read downloaded terrain") from exc
    if signature not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        raise TerrainAcquisitionError("Downloaded terrain is not a TIFF raster")
    try:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds

        with rasterio.open(path) as dataset:
            if dataset.width <= 0 or dataset.height <= 0 or dataset.count < 1:
                raise TerrainAcquisitionError("Downloaded raster has invalid dimensions")
            if dataset.crs is None:
                raise TerrainAcquisitionError("Downloaded raster has no CRS")
            west, south, east, north = transform_bounds(
                dataset.crs, "EPSG:4326", *dataset.bounds, densify_pts=21
            )
            intersects = not (
                east < expected.west
                or west > expected.east
                or north < expected.south
                or south > expected.north
            )
            if not intersects:
                raise TerrainAcquisitionError(
                    "Downloaded raster does not intersect the survey bounds"
                )
            values = dataset.read(1, masked=True)
            finite = np.isfinite(values.compressed())
            if values.count() == 0 or not np.any(finite):
                raise TerrainAcquisitionError(
                    "Downloaded raster contains no finite surface elevations"
                )
    except TerrainAcquisitionError:
        raise
    except Exception as exc:
        raise TerrainAcquisitionError("Downloaded GeoTIFF validation failed") from exc


def acquire_terrain_for_area(
    area_file: str | Path | dict[str, Any],
    *,
    survey_crs: str,
    padding_m: float = 0.0,
    cache_dir: str | Path | None = None,
    timeout_s: float = 180.0,
    opener: Callable[..., Any] | None = None,
) -> Path:
    """Return a validated cached COP30 GeoTIFF for the survey geometry."""
    bounds = bbox_from_geojson(
        area_file, crs=survey_crs, padding_m=padding_m
    )
    destination_dir = _cache_directory(cache_dir)
    destination = _cache_path(bounds, destination_dir)
    if destination.is_file():
        _validate_geotiff(destination, bounds)
        return destination

    api_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
    if not api_key:
        raise TerrainAcquisitionError(
            "OPENTOPOGRAPHY_API_KEY is not visible in the execution environment"
        )
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and greater than zero")

    params = {
        "demtype": COP30_DATASET,
        "south": bounds.normalized()[1],
        "north": bounds.normalized()[3],
        "west": bounds.normalized()[0],
        "east": bounds.normalized()[2],
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    request = urllib.request.Request(
        _ENDPOINT + "?" + urllib.parse.urlencode(params),
        headers={
            "Accept": "image/tiff,application/octet-stream",
            "User-Agent": "planes-terrain-integration/1.0",
        },
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    open_request = opener or urllib.request.urlopen
    try:
        response = open_request(request, timeout=timeout_s)
        with response, part.open("wb") as output:
            while chunk := response.read(64 * 1024):
                output.write(chunk)
        if part.stat().st_size == 0:
            raise TerrainAcquisitionError("OpenTopography returned an empty response")
        _validate_geotiff(part, bounds)
        os.replace(part, destination)
        return destination
    except urllib.error.HTTPError as exc:
        raise TerrainAcquisitionError(
            f"OpenTopography request failed with HTTP {exc.code}"
        ) from None
    except urllib.error.URLError:
        raise TerrainAcquisitionError("OpenTopography request failed") from None
    except TerrainAcquisitionError:
        raise
    except Exception:
        raise TerrainAcquisitionError("OpenTopography acquisition failed") from None
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
