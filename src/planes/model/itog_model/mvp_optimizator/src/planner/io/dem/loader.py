"""Strict terrain-source selection by local file extension."""

from __future__ import annotations

from pathlib import Path

from planner.io.dem.base import BaseDEM, TerrainDataError
from planner.io.dem.flat import FlatDEM
from planner.io.dem.geotiff import GeoTiffDEM
from planner.io.dem.kml import KMLDem


_GEOTIFF_EXTS = {".tif", ".tiff", ".gtiff"}


def load_dem(
    path: str | Path | None,
    *,
    crs: str | None = None,
    horizontal_unit: str | None = None,
    elevation_unit: str | None = None,
) -> BaseDEM:
    """Load an intentional flat source or a strictly declared local terrain.

    ``None`` means terrain was intentionally omitted and preserves legacy flat
    behavior. Once a path is requested, all errors fail closed.
    """
    if path is None:
        return FlatDEM()
    if not crs or not horizontal_unit or not elevation_unit:
        raise TerrainDataError(
            "Requested terrain requires explicit CRS and horizontal/elevation units"
        )
    if elevation_unit != "metre":
        raise TerrainDataError("Terrain elevation_unit must be metre")

    source = Path(path)
    if not source.is_file():
        raise TerrainDataError(f"Terrain file not found: {source}")
    extension = source.suffix.lower()
    if extension == ".kml":
        return KMLDem.from_file(
            source,
            crs=crs,
            horizontal_unit=horizontal_unit,
            elevation_unit=elevation_unit,
        )
    if extension in _GEOTIFF_EXTS:
        if horizontal_unit not in {"degree", "metre"}:
            raise TerrainDataError(
                "GeoTIFF horizontal_unit must be degree or metre"
            )
        return GeoTiffDEM(source, expected_crs=crs)
    raise TerrainDataError(f"Unsupported terrain format: {extension or '<none>'}")
