"""Определение типа DEM по расширению файла."""

from __future__ import annotations

from pathlib import Path

from planner.io.dem.base import BaseDEM
from planner.io.dem.flat import FlatDEM
from planner.io.dem.kml import KMLDem
from planner.utils.logging import log_warn


_GEOTIFF_EXTS = {".tif", ".tiff", ".gtiff"}
_KML_EXTS = {".kml"}


def load_dem(path: str | Path | None) -> BaseDEM:
    """Загружает DEM из файла по расширению.

    Правила:
      - None / несуществующий файл → FlatDEM (с warning).
      - .kml → KMLDem.
      - .tif / .tiff / .gtiff → GeoTiffDEM. Если rasterio нет или файл
        не читается — FlatDEM с warning.
      - неизвестное расширение → пробуем как KML; если KML-парсер не
        нашёл точек — FlatDEM с warning.

    Все ошибки логируются. Возврат FlatDEM означает «рельеф не учитывается»,
    и вызывающий код может это заметить по is_empty() == True.
    """
    if path is None:
        return FlatDEM()

    path = Path(path)
    if not path.exists():
        log_warn(
            "io.dem",
            "DEM file not found, using flat terrain",
            path=str(path),
        )
        return FlatDEM()

    ext = path.suffix.lower()

    if ext in _KML_EXTS:
        dem = KMLDem.from_file(path)
        if dem.is_empty():
            log_warn(
                "io.dem",
                "KML file has no elevation points, using flat terrain",
                path=str(path),
            )
            return FlatDEM()
        return dem

    if ext in _GEOTIFF_EXTS:
        from planner.io.dem.geotiff import GeoTiffDEM

        dem = GeoTiffDEM(path)

        # Быстрая проверка без загрузки: файл есть, rasterio доступен.
        if not dem.is_available():
            log_warn(
                "io.dem",
                "GeoTIFF not available (rasterio missing or file unreadable), "
                "using flat terrain",
                path=str(path),
            )
            return FlatDEM()

        # Форсируем загрузку, чтобы проверить, что растр действительно
        # читается. Это платит один раз — потом h() кэшируется.
        if dem.is_empty():
            log_warn(
                "io.dem",
                "GeoTIFF could not be loaded, using flat terrain",
                path=str(path),
                error=dem.error,
            )
            return FlatDEM()

        return dem

    # Неизвестное расширение — пробуем KML (иногда .txt, .xml)
    dem = KMLDem.from_file(path)
    if not dem.is_empty():
        log_warn(
            "io.dem",
            f"unknown extension {ext!r}, parsed as KML",
            path=str(path),
        )
        return dem

    log_warn(
        "io.dem",
        f"unknown extension {ext!r} and not a valid KML, using flat terrain",
        path=str(path),
    )
    return FlatDEM()