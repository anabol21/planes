"""Определение типа DEM по расширению файла."""

from __future__ import annotations

from pathlib import Path

from planner.io.dem.base import BaseDEM
from planner.io.dem.flat import FlatDEM
from planner.io.dem.kml import KMLDem


_GEOTIFF_EXTS = {".tif", ".tiff", ".gtiff"}
_KML_EXTS = {".kml"}


def load_dem(path: str | Path | None) -> BaseDEM:
    """
    Загружает DEM из файла:
      - .kml → KMLDem
      - .tif / .tiff / .gtiff → GeoTiffDEM (ленивый импорт rasterio)
      - None / другое → FlatDEM
    """
    if path is None:
        return FlatDEM()

    path = Path(path)
    if not path.exists():
        return FlatDEM()

    ext = path.suffix.lower()

    if ext in _KML_EXTS:
        return KMLDem.from_file(path)

    if ext in _GEOTIFF_EXTS:
        # Импортируем только при использовании
        from planner.io.dem.geotiff import GeoTiffDEM
        dem = GeoTiffDEM(path)
        if dem.is_empty():
            return FlatDEM()
        return dem

    # Неизвестный формат — пытаемся как KML, иначе плоская земля
    try:
        return KMLDem.from_file(path)
    except Exception:
        return FlatDEM()