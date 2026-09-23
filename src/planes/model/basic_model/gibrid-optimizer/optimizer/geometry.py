"""Геометрические вычисления: высота, ширина полосы, генерация полос."""

from math import radians, degrees, cos, sin, atan2
from typing import List, Tuple

import numpy as np
from shapely.geometry import Polygon, LineString

from .models import InputData, Camera

R_EARTH = 6371000.0
Strip = Tuple[Tuple[float, float], Tuple[float, float]]  # (start, end) в (lat, lon)


def _local_xy(lon, lat, lon0, lat0):
    x = R_EARTH * radians(lon - lon0) * cos(radians(lat0))
    y = R_EARTH * radians(lat - lat0)
    return x, y


def _xy_to_lonlat(x, y, lon0, lat0):
    lon = lon0 + degrees(x / (R_EARTH * cos(radians(lat0))))
    lat = lat0 + degrees(y / R_EARTH)
    return lon, lat


def _rotate(pts, angle_deg):
    a = radians(angle_deg)
    c, s = cos(a), sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


def compute_altitude_m(gsd_cm_per_px: float, camera: Camera) -> float:
    """Высота полёта из GSD:  GSD = pixel_size · H / f  →  H = GSD · f / pixel_size.
    """
    gsd_m = gsd_cm_per_px / 100.0
    pixel_size_mm = camera.sensor_width_mm / camera.image_width_px
    return gsd_m * camera.focal_length_mm / pixel_size_mm


def compute_strip_width_m(gsd_cm_per_px: float, camera: Camera) -> float:
    """Ширина полосы на земле (перпендикулярно направлению полёта)."""
    gsd_m = gsd_cm_per_px / 100.0
    return gsd_m * camera.image_height_px


def generate_strips(input_data: InputData) -> List[Strip]:
    """Генерирует полосы покрытия области.

    Возвращает список полос; каждая полоса — (start_latlon, end_latlon).
    Все полосы снимаются в одном направлении (strip_direction_deg).
    """
    area = input_data.area
    ref_lon = float(np.mean([p[0] for p in area]))
    ref_lat = float(np.mean([p[1] for p in area]))

    xy = [_local_xy(lon, lat, ref_lon, ref_lat) for lon, lat in area]

    az = radians(input_data.survey.strip_direction_deg)
    dir_x, dir_y = sin(az), cos(az)
    rot_angle_deg = -degrees(atan2(dir_y, dir_x))

    xy_rot = _rotate(xy, rot_angle_deg)
    xs = [p[0] for p in xy_rot]
    ys = [p[1] for p in xy_rot]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    strip_width = compute_strip_width_m(
        input_data.gsd_cm_per_px, input_data.camera
    )
    step = strip_width * (1.0 - input_data.survey.side_overlap)
    if step <= 1e-6:
        raise ValueError("Шаг между полосами ≤ 0. Уменьшите side_overlap.")

    poly = Polygon(xy_rot)
    strips_rot: List[List[Tuple[float, float]]] = []

    y = miny + step / 2.0
    while y < maxy:
        line = LineString([(minx - 100.0, y), (maxx + 100.0, y)])
        inter = poly.intersection(line)
        if not inter.is_empty:
            if inter.geom_type == "LineString":
                strips_rot.append(list(inter.coords))
            elif inter.geom_type == "MultiLineString":
                for seg in inter.geoms:
                    strips_rot.append(list(seg.coords))
        y += step

    strips: List[Strip] = []
    for seg in strips_rot:
        seg_back = _rotate(seg, -rot_angle_deg)
        x_s, y_s = seg_back[0]
        x_e, y_e = seg_back[-1]
        lon_s, lat_s = _xy_to_lonlat(x_s, y_s, ref_lon, ref_lat)
        lon_e, lat_e = _xy_to_lonlat(x_e, y_e, ref_lon, ref_lat)
        strips.append(((lat_s, lon_s), (lat_e, lon_e)))

    return strips