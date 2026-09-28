"""Модуль ввода-вывода: каталог, GeoJSON, KML, DEM, отчёты."""

from planner.io.catalog import Catalog, get_default_catalog
from planner.io.dem import BaseDEM, FlatDEM, KMLDem, load_dem
from planner.io.geo import (
    read_areas_geojson,
    read_no_fly_zones_geojson,
)
from planner.io.geojson_out import write_routes_geojson
from planner.io.json_out import write_report_json
from planner.io.kml_in import (
    read_no_fly_zones_kml,
    read_obstacles_kml,
)
from planner.io.kml_out import write_routes_kml
from planner.io.loaders import load_mission


__all__ = [
    # catalog
    "Catalog",
    "get_default_catalog",
    # DEM
    "BaseDEM",
    "FlatDEM",
    "KMLDem",
    "load_dem",
    # GeoJSON чтение
    "read_areas_geojson",
    "read_no_fly_zones_geojson",
    # KML чтение
    "read_obstacles_kml",
    "read_no_fly_zones_kml",
    # Загрузка миссии
    "load_mission",
    # Экспорт
    "write_routes_kml",
    "write_routes_geojson",
    "write_report_json",
]