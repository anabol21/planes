"""Чтение GeoJSON: области и запретные зоны.

Поддерживаются опциональные свойства:
  - survey_type: visible | multispectral | thermal
  - gsd_cm_per_px: свой GSD для области
  - uav_id: явная привязка к борту
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planner.models import Area, NoFlyZone, SurveyType


def read_areas_geojson(path: str | Path) -> list[Area]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        raise ValueError("area.geojson must be a FeatureCollection")

    areas: list[Area] = []
    for feature in data.get("features", []):
        props: dict[str, Any] = feature.get("properties", {}) or {}
        geom = feature.get("geometry")
        if geom is None or geom.get("type") != "Polygon":
            raise ValueError("Area geometry must be a Polygon")

        # --- Опциональный gsd_cm_per_px ---
        gsd_raw = props.get("gsd_cm_per_px")
        gsd: float | None = None
        if gsd_raw is not None:
            try:
                gsd = float(gsd_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Area {props.get('id')!r}: "
                    f"gsd_cm_per_px={gsd_raw!r} не число"
                )

        # --- Опциональный uav_id ---
        uav_id_raw = props.get("uav_id")
        uav_id: str | None = None
        if uav_id_raw:
            uav_id = str(uav_id_raw)

        area = Area(
            id=str(props.get("id") or f"area-{len(areas) + 1}"),
            name=str(props.get("name") or ""),
            survey_type=SurveyType(props.get("survey_type", "visible")),
            polygon=geom,
            gsd_cm_per_px=gsd,
            uav_id=uav_id,
        )
        areas.append(area)

    if not areas:
        raise ValueError("No areas found in GeoJSON")
    return areas


def read_no_fly_zones_geojson(path: str | Path) -> list[NoFlyZone]:
    """Читает запретные зоны из GeoJSON.

    Формат — FeatureCollection с Polygon-фичами. Properties
    опциональны: id, name.

    Возвращает пустой список, если файл не найден или пуст
    (в отличие от read_areas_geojson, не падает).
    """
    path = Path(path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        raise ValueError(
            "no_fly_zones.geojson must be a FeatureCollection"
        )

    zones: list[NoFlyZone] = []
    for feature in data.get("features", []):
        props: dict[str, Any] = feature.get("properties", {}) or {}
        geom = feature.get("geometry")
        if geom is None or geom.get("type") != "Polygon":
            # Пропускаем не-Polygon фичи с warning
            continue

        zone = NoFlyZone(
            id=str(props.get("id") or f"nfz-{len(zones) + 1}"),
            name=str(props.get("name") or ""),
            polygon=geom,
        )
        zones.append(zone)

    return zones