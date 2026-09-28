"""Сборка MissionInput из файлов фикстуры (+ опциональные DEM и NFZ).

Структура фикстуры:
    area.geojson           — обязательно
    obstacles.kml          — обязательно (может быть пустым)
    no_fly_zones.kml       — ОПЦИОНАЛЬНО (запретки)
    no_fly_zones.geojson   — ОПЦИОНАЛЬНО (альтернатива KML)
    vpp.json               — обязательно
    uav.json               — обязательно
    params.json            — обязательно
    dem.kml / *.tif        — опционально

Приоритет запреток: если есть .geojson — используется он,
иначе .kml, иначе пустой список.

Валидация:
  - борт ↔ ВПП ↔ камера (совместимость);
  - survey_type областей поддерживается бортами.
"""

from __future__ import annotations

import json
from pathlib import Path

from planner.io.catalog import Catalog, get_default_catalog
from planner.io.dem import load_dem
from planner.io.geo import (
    read_areas_geojson,
    read_no_fly_zones_geojson,
)
from planner.io.kml_in import (
    read_no_fly_zones_kml,
    read_obstacles_kml,
)
from planner.models import (
    Area,
    MissionInput,
    NoFlyZone,
    Params,
    UAVConfig,
    VPP,
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# Валидация совместимости
# ============================================================

def _validate_vpp_compatibility(
    uavs: list[UAVConfig],
    vpps: list[VPP],
    areas: list[Area],
    catalog: Catalog,
) -> None:
    """Проверяет совместимость борт ↔ ВПП ↔ камера."""
    vpp_by_id = {v.id: v for v in vpps}

    for uav in uavs:
        vpp = vpp_by_id.get(uav.vpp_id)
        if vpp is None:
            raise ValueError(
                f"UAV {uav.id!r}: vpp_id={uav.vpp_id!r} не найден "
                f"в vpp.json. Доступные ВПП: {sorted(vpp_by_id)}"
            )

        allowed_cameras = set(vpp.cameras or [])
        if allowed_cameras and uav.camera_id not in allowed_cameras:
            raise ValueError(
                f"UAV {uav.id!r}: камера {uav.camera_id!r} "
                f"не разрешена на ВПП {vpp.id!r}. "
                f"Разрешены: {sorted(allowed_cameras)}"
            )

        allowed_uavs = set(vpp.uavs or [])
        if allowed_uavs and uav.id not in allowed_uavs:
            raise ValueError(
                f"UAV {uav.id!r}: не разрешён на ВПП {vpp.id!r}. "
                f"Разрешены: {sorted(allowed_uavs)}"
            )

    if uavs:
        for area in areas:
            supported = any(
                catalog.camera_supports(u.camera_id, area.survey_type)
                for u in uavs
            )
            if not supported:
                cameras_in_mission = sorted({u.camera_id for u in uavs})
                raise ValueError(
                    f"Area {area.id!r}: survey_type="
                    f"{area.survey_type.value!r} не поддерживается "
                    f"ни одним бортом миссии. "
                    f"Камеры в миссии: {cameras_in_mission}"
                )


# ============================================================
# Запретные зоны
# ============================================================

def _load_no_fly_zones(fixtures: Path) -> list[NoFlyZone]:
    """Загружает запретные зоны из фикстуры.

    Приоритет:
      1. no_fly_zones.geojson — если есть.
      2. no_fly_zones.kml     — если есть.
      3. []                    — если ничего нет.

    Возвращает [] при отсутствии файлов. Не падает, если файл
    есть, но пустой.
    """
    geojson_path = fixtures / "no_fly_zones.geojson"
    if geojson_path.exists():
        return read_no_fly_zones_geojson(geojson_path)

    kml_path = fixtures / "no_fly_zones.kml"
    if kml_path.exists():
        return read_no_fly_zones_kml(kml_path)

    return []


# ============================================================
# Основная функция загрузки
# ============================================================

def load_mission(fixtures_dir: str | Path) -> MissionInput:
    fixtures = Path(fixtures_dir)
    if not fixtures.is_dir():
        raise NotADirectoryError(f"Fixtures dir not found: {fixtures}")

    # 1. Области
    areas = read_areas_geojson(fixtures / "area.geojson")

    # 2. Препятствия
    obstacles = read_obstacles_kml(fixtures / "obstacles.kml")

    # 3. Запретные зоны (опционально)
    no_fly_zones = _load_no_fly_zones(fixtures)

    # 4. ВПП
    vpp_data = _read_json(fixtures / "vpp.json")
    vpps = [VPP(**v) for v in vpp_data.get("vpps", [])]
    if not vpps:
        raise ValueError("vpp.json has no VPPs")

    # 5. Борта
    uav_data = _read_json(fixtures / "uav.json")
    uavs = [UAVConfig(**u) for u in uav_data.get("uavs", [])]
    if not uavs:
        raise ValueError("uav.json has no UAVs")

    # 6. Параметры
    params_data = _read_json(fixtures / "params.json")
    params = Params(**params_data)

    # 7. DEM
    dem = None
    if params.dem_file:
        dem_path = Path(params.dem_file)
        if not dem_path.is_absolute():
            dem_path = fixtures / dem_path
        dem_obj = load_dem(dem_path)
        if not dem_obj.is_empty():
            dem = dem_obj

    # 8. Каталог — проверка существования моделей
    catalog = get_default_catalog()
    for u in uavs:
        catalog.get_aircraft(u.model)
        catalog.get_camera(u.camera_id)

    # 9. Совместимость борт ↔ ВПП ↔ камера
    _validate_vpp_compatibility(uavs, vpps, areas, catalog)

    return MissionInput(
        areas=areas,
        obstacles=obstacles,
        no_fly_zones=no_fly_zones,
        vpps=vpps,
        uavs=uavs,
        params=params,
        dem=dem,
    )