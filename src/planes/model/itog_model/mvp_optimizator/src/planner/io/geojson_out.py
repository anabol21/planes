"""Экспорт маршрутов в GeoJSON.

Формат: FeatureCollection с фичами:
  - LineString — маршрут каждого вылета (waypoints);
  - Point — ВПП;
  - Polygon — область съёмки (kind=area);
  - Polygon — препятствие (kind=obstacle);
  - Polygon — запретная зона (kind=no_fly_zone);
  - LineString — полоса (kind=swath, опционально).

CRS — WGS84 (lon, lat), как требует GeoJSON RFC 7946.
"""

from __future__ import annotations

import json
from pathlib import Path

from planner.models import (
    Candidate,
    MissionInput,
    NoFlyZone,
    Obstacle,
    Swath,
)


def _route_to_feature(route, mission: MissionInput) -> dict:
    coords = [
        [float(p.lon), float(p.lat)] for p in route.waypoints
    ]

    feature = {
        "type": "Feature",
        "properties": {
            "uav_id": route.uav_id,
            "flight_index": route.flight_index,
            "vpp_id": route.vpp_id,
            "n_swaths": len(route.swath_ids),
            "T_air_s": round(route.T_air_s, 2),
            "T_total_s": round(route.T_total_s, 2),
            "E_wh": round(route.E_wh, 3),
            "mass_kg": round(route.mass_kg, 3),
            "T_charge_s": round(route.T_charge_s, 1),
            "total_climb_m": round(route.total_climb_m, 1),
            "total_descent_m": round(route.total_descent_m, 1),
            "h_asl_min_m": round(route.h_asl_min_m, 1),
            "h_asl_max_m": round(route.h_asl_max_m, 1),
            "swath_ids": list(route.swath_ids),
            "kind": "route",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        } if len(coords) >= 2 else None,
    }
    return feature


def _vpp_to_feature(vpp) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": vpp.id,
            "name": vpp.name,
            "alt_m": vpp.alt_m,
            "kind": "vpp",
            "uavs": list(vpp.uavs),
            "cameras": list(vpp.cameras),
        },
        "geometry": {
            "type": "Point",
            "coordinates": [float(vpp.lon), float(vpp.lat)],
        },
    }


def _area_to_feature(area) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": area.id,
            "name": area.name,
            "survey_type": area.survey_type.value,
            "gsd_cm_per_px": area.gsd_cm_per_px,
            "uav_id": area.uav_id,
            "kind": "area",
        },
        "geometry": area.polygon,
    }


def _obstacle_to_feature(obs: Obstacle) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": obs.id,
            "name": obs.name,
            "height_m": obs.height_m,
            "kind": "obstacle",
        },
        "geometry": obs.polygon,
    }


def _no_fly_zone_to_feature(nfz: NoFlyZone) -> dict:
    """Запретная зона — Polygon с kind=no_fly_zone."""
    return {
        "type": "Feature",
        "properties": {
            "id": nfz.id,
            "name": nfz.name,
            "kind": "no_fly_zone",
            "note": "flights forbidden at any altitude",
        },
        "geometry": nfz.polygon,
    }


def _swath_to_feature(swath: Swath) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": swath.id,
            "area_id": swath.area_id,
            "length_m": round(swath.length_m, 2),
            "h_agl_m": round(swath.h_agl_m, 2),
            "h_asl_m": round(swath.h_asl_m, 2),
            "n_photos": swath.n_photos,
            "feasible": swath.feasible,
            "kind": "swath",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [float(swath.start.lon), float(swath.start.lat)],
                [float(swath.end.lon), float(swath.end.lat)],
            ],
        },
    }


def build_geojson(
    mission: MissionInput,
    candidate: Candidate,
    swaths_by_id: dict[str, Swath] | None = None,
    include_areas: bool = True,
    include_obstacles: bool = True,
    include_no_fly_zones: bool = True,
    include_swaths: bool = False,
) -> dict:
    """Собирает FeatureCollection из mission и candidate."""
    features: list[dict] = []

    # 1. Маршруты
    for route in candidate.routes:
        feat = _route_to_feature(route, mission)
        if feat["geometry"] is not None:
            features.append(feat)

    # 2. ВПП
    for vpp in mission.vpps:
        features.append(_vpp_to_feature(vpp))

    # 3. Области
    if include_areas:
        for area in mission.areas:
            features.append(_area_to_feature(area))

    # 4. Препятствия
    if include_obstacles and mission.obstacles:
        for obs in mission.obstacles:
            features.append(_obstacle_to_feature(obs))

    # 5. Запретные зоны
    if include_no_fly_zones and mission.no_fly_zones:
        for nfz in mission.no_fly_zones:
            features.append(_no_fly_zone_to_feature(nfz))

    # 6. Полосы
    if include_swaths and swaths_by_id:
        for swath in swaths_by_id.values():
            features.append(_swath_to_feature(swath))

    meta = {
        "theta_best_deg": candidate.theta_deg,
        "decomposition_method": candidate.decomposition_method.value
        if hasattr(candidate.decomposition_method, "value")
        else str(candidate.decomposition_method),
        "C_max_s": round(candidate.C_max_s, 2),
        "flight_hours_s": round(candidate.flight_hours_s, 2),
        "energy_total_wh": round(candidate.energy_total_wh, 3),
        "n_uavs_used": candidate.n_uavs_used,
        "n_routes": len(candidate.routes),
        "n_no_fly_zones": len(mission.no_fly_zones),
    }

    return {
        "type": "FeatureCollection",
        "name": "geoscan_planner_routes",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "metadata": meta,
        "features": features,
    }


def write_routes_geojson(
    path: str | Path,
    mission: MissionInput,
    candidate: Candidate,
    swaths_by_id: dict[str, Swath] | None = None,
    include_areas: bool = True,
    include_obstacles: bool = True,
    include_no_fly_zones: bool = True,
    include_swaths: bool = False,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = build_geojson(
        mission=mission,
        candidate=candidate,
        swaths_by_id=swaths_by_id,
        include_areas=include_areas,
        include_obstacles=include_obstacles,
        include_no_fly_zones=include_no_fly_zones,
        include_swaths=include_swaths,
    )

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)