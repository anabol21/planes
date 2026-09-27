"""DEM из GeoTIFF: растровая модель рельефа (Copernicus, SRTM, LiDAR).

Ленивая загрузка: растр читается при первом обращении к h() или is_empty().
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from planner.io.dem.base import BaseDEM


class GeoTiffDEM(BaseDEM):
    """DEM из GeoTIFF с билинейной интерполяцией.

    Состояния:
      - _attempted = False, _loaded = False — ещё не пытались загрузить
      - _attempted = True,  _loaded = False — попытка была, но упала
      - _attempted = True,  _loaded = True  — растр в памяти

    Повторные вызовы h() после успешной загрузки не читают файл.
    После неудачной попытки повторно не пытаются — состояние фиксируется.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._arr: np.ndarray | None = None
        self._transform = None
        self._crs = None
        self._nodata: float | None = None
        self._bounds = None
        self._attempted = False
        self._loaded = False
        self._error: str | None = None

    # --------------------------------------------------
    # Ленивая загрузка
    # --------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._attempted:
            return
        self._attempted = True

        if not self.path.exists():
            self._error = f"GeoTIFF not found: {self.path}"
            return

        try:
            import rasterio  # ленивый импорт
        except ImportError:
            self._error = (
                "rasterio not installed. "
                "Install with: pip install rasterio"
            )
            return

        try:
            with rasterio.open(self.path) as src:
                self._arr = src.read(1).astype(np.float32)
                self._transform = src.transform
                self._crs = src.crs
                self._nodata = src.nodata
                self._bounds = src.bounds
            self._loaded = True
        except Exception as e:
            self._error = f"Failed to read GeoTIFF: {e}"

    # --------------------------------------------------
    # Быстрая проверка без загрузки
    # --------------------------------------------------

    def is_available(self) -> bool:
        """True, если файл есть и rasterio установлен.

        Не читает растр. Используется в loader.py для быстрого решения,
        подменять ли DEM на FlatDEM.
        """
        if not self.path.exists():
            return False
        try:
            import rasterio  # noqa: F401
            return True
        except ImportError:
            return False

    # --------------------------------------------------
    # h(lat, lon)
    # --------------------------------------------------

    def h(self, lat: float, lon: float) -> float:
        self._ensure_loaded()

        if self._arr is None or self._transform is None:
            return 0.0

        # Пиксельные координаты (float)
        col_f, row_f = ~self._transform * (lon, lat)

        rows, cols = self._arr.shape
        if not (0 <= col_f < cols and 0 <= row_f < rows):
            # Точка вне растра — берём ближайший крайний пиксель
            col_f = min(max(col_f, 0), cols - 1.001)
            row_f = min(max(row_f, 0), rows - 1.001)

        col = int(math.floor(col_f))
        row = int(math.floor(row_f))
        fx = col_f - col
        fy = row_f - row

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
        # NaN → 0 (встречается в Copernicus DEM)
        if np.isnan(val):
            return 0.0
        return val

    # --------------------------------------------------
    # Утилиты
    # --------------------------------------------------

    def is_empty(self) -> bool:
        """True, если растр не загружен (файл отсутствует, ошибка или нет rasterio)."""
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
        """Сообщение об ошибке загрузки, если она была.

        Не запускает загрузку — возвращает то, что уже известно.
        Для получения актуального состояния вызовите is_empty().
        """
        return self._error