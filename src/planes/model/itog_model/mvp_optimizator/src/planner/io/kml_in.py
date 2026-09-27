"""Чтение KML: препятствия с высотами.

Поддерживаются:
  - Polygon (footprint препятствия);
  - Point (точечное препятствие — превращается в квадрат 10×10 м);
  - MultiGeometry (разворачивается в несколько препятствий).

Высота извлекается из <description> в свободной форме:
  height=50, Height: 50, высота 50, h=50, 50 m.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from planner.models import Obstacle


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

# Радиус точечного препятствия по умолчанию (метры).
# Point в KML не имеет площади, но obstacle_buffer_m в pipeline даст
# дополнительный отступ. 5 м — консервативно, чтобы не потерять объект.
POINT_OBSTACLE_RADIUS_M = 5.0

# 1 градус широты ≈ 111 320 м. Для долготы на широте φ: 111320·cos(φ).
_M_PER_DEG_LAT = 111_320.0


# ============================================================
# Парсинг высоты
# ============================================================

_HEIGHT_RE = re.compile(
    r"""
    (?:
        height | высота | h
    )
    \s*
    (?:[=:]|\s)
    \s*
    (?P<val>\d+(?:[.,]\d+)?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Второй шаблон: просто "50 m", "50 м" — если ключевого слова нет
_HEIGHT_M_RE = re.compile(
    r"(?P<val>\d+(?:[.,]\d+)?)\s*(?:m\b|м\b|meters?|метров?|м\.)",
    re.IGNORECASE,
)


def _parse_height(description: str | None) -> float:
    """Извлекает высоту из свободного текста описания.

    Поддерживаемые формы:
      - height=50
      - Height: 50
      - высота 50
      - h=50
      - 50 m
      - 50 м

    Возвращает 0.0, если высота не найдена.
    """
    if not description:
        return 0.0

    text = str(description).replace(",", ".")

    m = _HEIGHT_RE.search(text)
    if m:
        try:
            return float(m.group("val"))
        except ValueError:
            pass

    m = _HEIGHT_M_RE.search(text)
    if m:
        try:
            return float(m.group("val"))
        except ValueError:
            pass

    return 0.0


# ============================================================
# Парсинг координат
# ============================================================

def _parse_coords_text(coords_text: str) -> list[tuple[float, float, float]]:
    """'lon,lat,alt lon,lat,alt ...' → [(lon, lat, alt), ...].

    Пропускает некорректные токены. Возвращает пустой список, если
    ни одного валидного токена нет.
    """
    points: list[tuple[float, float, float]] = []
    if not coords_text:
        return points

    for chunk in coords_text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else 0.0
        except ValueError:
            continue
        points.append((lon, lat, alt))

    return points


def _close_ring(pts: list[list[float]]) -> list[list[float]]:
    """Замыкает ring, если первая и последняя точки различаются."""
    if not pts:
        return pts
    if pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    return pts


def _coords_to_polygon(coords_text: str) -> dict | None:
    """Строка координат → GeoJSON Polygon.

    Возвращает None, если точек меньше 3.
    """
    raw = _parse_coords_text(coords_text)
    if len(raw) < 3:
        return None

    pts: list[list[float]] = [[lon, lat] for lon, lat, _ in raw]
    pts = _close_ring(pts)
    return {"type": "Polygon", "coordinates": [pts]}


def _point_to_polygon(
    coords_text: str,
    radius_m: float = POINT_OBSTACLE_RADIUS_M,
) -> dict | None:
    """Точка → квадрат вокруг неё (для Point-препятствий).

    Использует локальное приближение: 1° lat ≈ 111 320 м,
    1° lon ≈ 111 320·cos(lat). Для маленького радиуса (10 м)
    этого достаточно.
    """
    raw = _parse_coords_text(coords_text)
    if not raw:
        return None

    lon, lat, _ = raw[0]

    import math
    dlat = radius_m / _M_PER_DEG_LAT
    dlon = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))

    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


# ============================================================
# Разбор одного Placemark
# ============================================================

def _placemark_geometries(placemark) -> list[dict]:
    """Возвращает список GeoJSON-полигонов из одного Placemark.

    Обрабатывает Polygon, Point и MultiGeometry. Игнорирует всё
    остальное (LineString, LinearRing как самостоятельный объект).
    """
    geoms: list[dict] = []

    # --- Polygon ---
    for poly in placemark.findall(".//kml:Polygon", KML_NS):
        coords_el = poly.find(
            ".//kml:outerBoundaryIs//kml:LinearRing//kml:coordinates",
            KML_NS,
        )
        if coords_el is None or coords_el.text is None:
            continue
        geom = _coords_to_polygon(coords_el.text.strip())
        if geom is not None:
            geoms.append(geom)

    # --- Point ---
    for point in placemark.findall(".//kml:Point", KML_NS):
        coords_el = point.find("kml:coordinates", KML_NS)
        if coords_el is None or coords_el.text is None:
            continue
        geom = _point_to_polygon(coords_el.text.strip())
        if geom is not None:
            geoms.append(geom)

    return geoms


# ============================================================
# Основная функция
# ============================================================

def read_obstacles_kml(path: str | Path) -> list[Obstacle]:
    """Читает KML с препятствиями.

    Возвращает список Obstacle. Один Placemark с MultiGeometry
    может дать несколько Obstacle (id с суффиксом -1, -2, ...).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"KML not found: {path}")

    tree = etree.parse(str(path))
    root = tree.getroot()

    obstacles: list[Obstacle] = []

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name_el = placemark.find("kml:name", KML_NS)
        desc_el = placemark.find("kml:description", KML_NS)

        name = ""
        if name_el is not None and name_el.text:
            name = name_el.text.strip()

        desc = ""
        if desc_el is not None and desc_el.text:
            desc = desc_el.text.strip()

        height = _parse_height(desc)

        geoms = _placemark_geometries(placemark)
        if not geoms:
            continue

        base_id = name or f"obs-{len(obstacles) + 1}"

        for k, geom in enumerate(geoms):
            # Один Placemark — один Obstacle. Несколько геометрий
            # в MultiGeometry получают суффиксы -1, -2, ...
            obs_id = base_id if len(geoms) == 1 else f"{base_id}-{k + 1}"

            obstacles.append(
                Obstacle(
                    id=obs_id,
                    name=name,
                    height_m=height,
                    polygon=geom,
                )
            )

    return obstacles