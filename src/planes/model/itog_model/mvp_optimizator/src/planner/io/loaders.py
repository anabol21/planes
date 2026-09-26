"""Сборка MissionInput из пяти файлов (+ опциональный DEM)."""

from __future__ import annotations

import json
from pathlib import Path

from planner.io.catalog import get_default_catalog
from planner.io.dem import load_dem
from planner.io.geo import read_areas_geojson
from planner.io.kml_in import read_obstacles_kml
from planner.models import (
    MissionInput,
    Params,
    UAVConfig,
    VPP,
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_mission(fixtures_dir: str | Path) -> MissionInput:
    fixtures = Path(fixtures_dir)
    if not fixtures.is_dir():
        raise NotADirectoryError(f"Fixtures dir not found: {fixtures}")

    # 1. Области
    areas = read_areas_geojson(fixtures / "area.geojson")

    # 2. Препятствия
    obstacles = read_obstacles_kml(fixtures / "obstacles.kml")

    # 3. ВПП
    vpp_data = _read_json(fixtures / "vpp.json")
    vpps = [VPP(**v) for v in vpp_data.get("vpps", [])]
    if not vpps:
        raise ValueError("vpp.json has no VPPs")

    # 4. Борта
    uav_data = _read_json(fixtures / "uav.json")
    uavs = [UAVConfig(**u) for u in uav_data.get("uavs", [])]
    if not uavs:
        raise ValueError("uav.json has no UAVs")

    # 5. Параметры
    params_data = _read_json(fixtures / "params.json")
    params = Params(**params_data)

    # 6. DEM
    dem = None
    if params.dem_file:
        dem_path = Path(params.dem_file)
        if not dem_path.is_absolute():
            dem_path = fixtures / dem_path
        dem = load_dem(
            dem_path,
            crs=params.dem_crs,
            horizontal_unit=params.dem_horizontal_unit,
            elevation_unit=params.dem_elevation_unit,
        )

    # Проверка каталога
    catalog = get_default_catalog()
    for u in uavs:
        catalog.get_aircraft(u.model)
        catalog.get_camera(u.camera_id)

    return MissionInput(
        areas=areas,
        obstacles=obstacles,
        vpps=vpps,
        uavs=uavs,
        params=params,
        dem=dem,
    )
