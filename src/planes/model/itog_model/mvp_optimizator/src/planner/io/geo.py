"""Чтение GeoJSON: области."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planner.models import Area, SurveyType


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

        area = Area(
            id=str(props.get("id") or f"area-{len(areas) + 1}"),
            name=str(props.get("name") or ""),
            survey_type=SurveyType(props.get("survey_type", "visible")),
            polygon=geom,
        )
        areas.append(area)

    if not areas:
        raise ValueError("No areas found in GeoJSON")
    return areas