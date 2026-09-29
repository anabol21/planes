"""Attach a cached COP30 GeoTIFF to the isolated F2C solve scenario.

The live iso path does not require the browser to send a DEM path. When
``dem_file`` / aliases are already a readable file, standalone callers leave
them alone. The live bridge requires terrain and validates an existing file
against its canonical rectangle before reuse. That geometry is acquired with
zero padding. Standalone callers without a geometry factory retain the
historical survey-bbox policy.

Standalone default policy is degrade-to-mono: acquisition failures become
limitation lines and the worker keeps flat ``h=0``. The live bridge requires
terrain regardless of ``PLANES_DEM_FAIL_CLOSED``. This is not climb-time or a
terrain corridor.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Any

from planes.integration.kml.constraints import parse_survey_polygon
from planes.integration.terrain.opentopography import (
    TerrainAcquisitionError,
    _validate_geotiff,
    acquire_terrain_for_area,
    bbox_from_geojson,
)


DEM_PATH_KEYS = ("dem_file", "dem_geotiff", "dem_path", "dem")
_DEM_PLACEHOLDERS = frozenset({"mono", "flat", "none"})
_DEM_NESTED_KEYS = ("path", "file", "geotiff", "url_local")
DEFAULT_PADDING_M = 200.0
DEFAULT_CACHE_DIR = Path("/tmp/dems")
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_SKIP_NOTE = "iso path: existing readable dem_file used; OpenTopography was not called"
_ACQUIRED_NOTE = "iso path: OpenTopography COP30 acquired; dem_file set before isolated worker"
_TIME_NOTE = "iso duration remains 2D path/speed — climb/descent time NOT applied"
_CORRIDOR_NOTE = "terrain_corridor is not applied on the iso path"
_NO_GEOMETRY_NOTE = (
    "temporary flat terrain; iso path could not derive a survey bbox; "
    "OpenTopography was not called"
)
_FALLBACK_PREFIX = "temporary flat terrain; OpenTopography acquisition failed"


def fail_closed() -> bool:
    return os.environ.get("PLANES_DEM_FAIL_CLOSED", "").strip().lower() in _TRUTHY


def dem_padding_m() -> float:
    raw = os.environ.get("PLANES_DEM_PADDING_M")
    if raw is None or not raw.strip():
        return DEFAULT_PADDING_M
    value = float(raw)
    if value < 0:
        raise ValueError("PLANES_DEM_PADDING_M must be non-negative")
    return value


def dem_cache_dir() -> Path:
    for key in ("PLANES_DEM_CACHE", "PLANES_TERRAIN_CACHE_DIR"):
        raw = os.environ.get(key)
        if raw and raw.strip():
            return Path(raw.strip())
    return DEFAULT_CACHE_DIR


def existing_readable_dem_path(scenario: dict[str, Any]) -> Path | None:
    """Return a readable DEM path already present on the scenario, if any."""
    raw = _raw_dem_value(scenario)
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if path.is_file() and path.stat().st_size > 0:
        return path.resolve()
    return None


def survey_geometry_from_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Build EPSG:4326 Polygon/MultiPolygon from survey_kml or areas."""
    survey_kml = scenario.get("survey_kml")
    if isinstance(survey_kml, str) and survey_kml.strip():
        return _polygons_to_geojson(parse_survey_polygon(survey_kml))
    areas = scenario.get("areas")
    if isinstance(areas, list) and areas:
        return _areas_to_geojson(areas)
    raise ValueError("scenario needs survey_kml or areas to derive a DEM bbox")


def ensure_dem_for_iso_scenario(
    scenario: dict[str, Any],
    *,
    acquire: Callable[..., Path] | None = None,
    geometry_factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    require_terrain: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Set ``scenario.dem_file`` when a GeoTIFF can be reused or acquired.

    Returns the same scenario dict (mutated) plus limitation notes for the
    bridge to append. Does not claim 3D time or a terrain corridor.
    """
    notes: list[str] = []
    existing = None if require_terrain else existing_readable_dem_path(scenario)
    if existing is not None:
        scenario["dem_file"] = str(existing)
        notes.append(_SKIP_NOTE)
        notes.append(f"dem_file: {existing}")
        notes.append(_TIME_NOTE)
        return scenario, notes

    try:
        geometry = (
            geometry_factory(scenario)
            if geometry_factory is not None
            else survey_geometry_from_scenario(scenario)
        )
        crs = str(scenario.get("crs") or "EPSG:4326")
        if require_terrain:
            supplied = _raw_dem_value(scenario)
            if supplied is not None:
                existing = Path(supplied).expanduser()
                bounds = bbox_from_geojson(geometry, crs=crs)
                _validate_geotiff(existing, bounds)
                existing = existing.resolve()
                scenario["dem_file"] = str(existing)
                notes.extend((_SKIP_NOTE, f"dem_file: {existing}", _TIME_NOTE))
                return scenario, notes
        acquire_fn = acquire or acquire_terrain_for_area
        path = Path(
            acquire_fn(
                geometry,
                survey_crs=crs,
                padding_m=0.0 if geometry_factory is not None else dem_padding_m(),
                cache_dir=dem_cache_dir(),
            )
        )
        scenario["dem_file"] = str(path)
        notes.append(_ACQUIRED_NOTE)
        notes.append(f"dem_file: {path}")
        notes.append(_TIME_NOTE)
        if scenario.get("terrain_corridor"):
            notes.append(_CORRIDOR_NOTE)
        return scenario, notes
    except (TerrainAcquisitionError, ValueError, OSError) as exc:
        if require_terrain or fail_closed():
            if isinstance(exc, TerrainAcquisitionError):
                raise
            raise TerrainAcquisitionError(str(exc)) from exc
        notes.append(_fallback_note(exc))
        notes.append("dem_file: mono")
        notes.append(_TIME_NOTE)
        return scenario, notes


def _raw_dem_value(scenario: dict[str, Any]) -> str | None:
    for key in DEM_PATH_KEYS:
        raw = scenario.get(key)
        path = _as_path_string(raw)
        if path is not None:
            return path
    return None


def _as_path_string(raw: object) -> str | None:
    if isinstance(raw, str):
        text = raw.strip()
        if text and text.lower() not in _DEM_PLACEHOLDERS:
            return text
        return None
    if isinstance(raw, dict):
        for sub in _DEM_NESTED_KEYS:
            nested = raw.get(sub)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _polygons_to_geojson(polygons: list[Any]) -> dict[str, Any]:
    coordinates = [[[[lon, lat] for lon, lat in polygon.ring]] for polygon in polygons]
    if not coordinates:
        raise ValueError("survey geometry has no polygons")
    if len(coordinates) == 1:
        return {"type": "Polygon", "coordinates": coordinates[0]}
    return {"type": "MultiPolygon", "coordinates": coordinates}


def _areas_to_geojson(areas: list[Any]) -> dict[str, Any]:
    rings: list[list[list[list[float]]]] = []
    for index, area in enumerate(areas, start=1):
        if not isinstance(area, dict):
            raise ValueError(f"area {index} is not an object")
        poly = area.get("polygon") or area
        if not isinstance(poly, dict) or "coordinates" not in poly:
            raise ValueError(f"area {index} missing polygon.coordinates")
        rings.append(list(poly["coordinates"]))
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": rings[0]}
    return {"type": "MultiPolygon", "coordinates": rings}


def _fallback_note(exc: BaseException) -> str:
    if isinstance(exc, ValueError) and "survey_kml or areas" in str(exc):
        return _NO_GEOMETRY_NOTE
    return f"{_FALLBACK_PREFIX}: {exc}"
