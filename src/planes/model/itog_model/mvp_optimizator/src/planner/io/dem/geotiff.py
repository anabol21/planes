"""DEM из GeoTIFF: растровая модель рельефа (Copernicus, SRTM, LiDAR)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from planner.io.dem.base import BaseDEM


class GeoTiffDEM(BaseDEM):
    """DEM из GeoTIFF с билинейной интерполяцией."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._arr: np.ndarray | None = None
        self._transform = None
        self._crs = None
        self._nodata: float | None = None
        self._bounds = None
        self._loaded = False
        self._error: str | None = None

    # --------------------------------------------------
    # Ленивая загрузка
    # --------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if not self.path.exists():
            self._error = f"GeoTIFF not found: {self.path}"
            return

        try:
            import rasterio  # ленивый импорт
        except ImportError:
            self._error = "rasterio not installed"
            return

        try:
            with rasterio.open(self.path) as src:
                self._arr = src.read(1).astype(np.float32)
                self._transform = src.transform
                self._crs = src.crs
                self._nodata = src.nodata
                self._bounds = src.bounds
        except Exception as e:
            self._error = f"Failed to read GeoTIFF: {e}"

    # --------------------------------------------------
    # h(lat, lon)
    # --------------------------------------------------

    def h(self, lat: float, lon: float) -> float:
        self._ensure_loaded()

        if self._arr is None or self._transform is None:
            return 0.0

        # Пиксельные координаты (float)
        col_f, row_f = ~self._transform * (lon, lat)

        # Clamp в границы растра
        rows, cols = self._arr.shape
        if not (0 <= col_f < cols and 0 <= row_f < rows):
            # Точка вне растра — берём ближайший крайний пиксель
            col_f = min(max(col_f, 0), cols - 1.001)
            row_f = min(max(row_f, 0), rows - 1.001)

        col = int(math.floor(col_f))
        row = int(math.floor(row_f))
        fx = col_f - col
        fy = row_f - row

        # Билинейная интерполяция по 4 пикселям
        c1 = min(col + 1, cols - 1)
        r1 = min(row + 1, rows - 1)

        h00 = self._get_pixel(row, col)
        h10 = self._get_pixel(row, c1)
        h01 = self._get_pixel(r1, col)
        h11 = self._get_pixel(r1, c1)

        return (
            h00 * (1 - fx) * (1 - fy)
            + h10 * fx * (1 - fy)
            + h01 * (1 - fx) * fy
            + h11 * fx * fy
        )

    def _get_pixel(self, row: int, col: int) -> float:
        val = float(self._arr[row, col])
        # nodata → 0
        if self._nodata is not None and abs(val - self._nodata) < 1e-3:
            return 0.0
        return val

    # --------------------------------------------------
    # Утилиты
    # --------------------------------------------------

    def is_empty(self) -> bool:
        self._ensure_loaded()
        return self._arr is None

    def h_max(self) -> float:
        self._ensure_loaded()
        if self._arr is None:
            return 0.0
        return float(np.nanmax(self._arr))

    def h_min(self) -> float:
        self._ensure_loaded()
        if self._arr is None:
            return 0.0
        return float(np.nanmin(self._arr))

    @property
    def error(self) -> str | None:
        self._ensure_loaded()
        return self._error