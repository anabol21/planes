"""Fail-closed local GeoTIFF surface provider with bilinear interpolation."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from planner.io.dem.base import BaseDEM, TerrainDataError, validate_elevation


class GeoTiffDEM(BaseDEM):
    """Read a finite, georeferenced raster and query it using WGS84 points."""

    def __init__(self, path: str | Path, *, expected_crs: str | None = None):
        self.path = Path(path)
        self.expected_crs = expected_crs
        self._arr: np.ndarray | None = None
        self._transform = None
        self._crs = None
        self._nodata: float | None = None
        self._bounds = None
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            raise TerrainDataError(f"GeoTIFF terrain file not found: {self.path}")
        try:
            import rasterio
            from rasterio.crs import CRS
        except ImportError as exc:
            raise TerrainDataError(
                "GeoTIFF terrain requires the declared rasterio dependency"
            ) from exc

        try:
            with rasterio.open(self.path) as src:
                if src.count < 1 or src.width <= 0 or src.height <= 0:
                    raise TerrainDataError("GeoTIFF has invalid dimensions")
                if src.crs is None:
                    raise TerrainDataError("GeoTIFF has no declared CRS")
                if self.expected_crs and src.crs != CRS.from_user_input(
                    self.expected_crs
                ):
                    raise TerrainDataError(
                        f"GeoTIFF CRS {src.crs} does not match declared "
                        f"{self.expected_crs}"
                    )
                transform_values = tuple(src.transform)[:6]
                if not all(math.isfinite(value) for value in transform_values):
                    raise TerrainDataError("GeoTIFF has a non-finite transform")
                if abs(src.transform.a * src.transform.e) < 1e-18:
                    raise TerrainDataError("GeoTIFF has a degenerate transform")

                self._arr = src.read(1).astype(np.float64)
                self._transform = src.transform
                self._crs = src.crs
                self._nodata = src.nodata
                self._bounds = src.bounds
        except TerrainDataError:
            raise
        except Exception as exc:
            raise TerrainDataError(f"Failed to read GeoTIFF: {self.path}") from exc

        valid = self._valid_mask(self._arr)
        if not np.any(valid):
            raise TerrainDataError("GeoTIFF contains no finite elevation samples")

    def _valid_mask(self, values: np.ndarray) -> np.ndarray:
        mask = np.isfinite(values)
        if self._nodata is not None and math.isfinite(float(self._nodata)):
            mask &= ~np.isclose(values, float(self._nodata))
        return mask

    def _query_xy(self, lat: float, lon: float) -> tuple[float, float]:
        from rasterio.warp import transform

        try:
            xs, ys = transform("EPSG:4326", self._crs, [lon], [lat])
        except Exception as exc:
            raise TerrainDataError("Could not transform WGS84 terrain query") from exc
        return float(xs[0]), float(ys[0])

    def h(self, lat: float, lon: float) -> float:
        lat = validate_elevation(lat, source="query latitude")
        lon = validate_elevation(lon, source="query longitude")
        x, y = self._query_xy(lat, lon)
        left, bottom, right, top = self._bounds
        if not (left <= x <= right and bottom <= y <= top):
            raise TerrainDataError("Terrain query is outside GeoTIFF coverage")

        col_corner, row_corner = ~self._transform * (x, y)
        col_f = float(col_corner) - 0.5
        row_f = float(row_corner) - 0.5
        rows, cols = self._arr.shape
        col_f = min(max(col_f, 0.0), cols - 1.0)
        row_f = min(max(row_f, 0.0), rows - 1.0)

        col0 = int(math.floor(col_f))
        row0 = int(math.floor(row_f))
        col1 = min(col0 + 1, cols - 1)
        row1 = min(row0 + 1, rows - 1)
        fx = col_f - col0
        fy = row_f - row0
        values = np.array(
            [
                self._arr[row0, col0],
                self._arr[row0, col1],
                self._arr[row1, col0],
                self._arr[row1, col1],
            ],
            dtype=float,
        )
        if not np.all(self._valid_mask(values)):
            raise TerrainDataError("GeoTIFF query intersects nodata")
        h00, h10, h01, h11 = values
        result = (
            h00 * (1 - fx) * (1 - fy)
            + h10 * fx * (1 - fy)
            + h01 * (1 - fx) * fy
            + h11 * fx * fy
        )
        return validate_elevation(result, source="GeoTIFF interpolation")

    def is_empty(self) -> bool:
        return False

    def h_max(self) -> float:
        return float(np.max(self._arr[self._valid_mask(self._arr)]))

    def h_min(self) -> float:
        return float(np.min(self._arr[self._valid_mask(self._arr)]))

    @property
    def crs(self) -> str:
        return str(self._crs)
