"""Isolated copy of planes.runtime.fields2cover_engine for F2C embed venv.

COPY only — listener /opt/planes is untouched. Local Candidate/Point/Route
stubs replace planner.models so mvp_optimizator/src (and sitecustomize.py)
is NEVER added to sys.path. Run under .venv-f2c-embed with clean PYTHONPATH.
Empty angles → SG_BruteForce.generateBestSwaths. This is pack/split F2C,
not full mvp LNS/assignment.
"""

from __future__ import annotations

import math
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

FIELDS2COVER_VERSION = "2.1.0"
_LAT_M_PER_DEG = 110540.0
_LON_M_PER_DEG = 111320.0
_MIN_CELL_AREA_M2 = 1.0


class BudgetExhausted(Exception):
    """The time budget ended before any route existed."""


@dataclass(frozen=True)
class BoardCamera:
    """One expanded board, with spacing taken from its own fleet camera."""

    uav_id: str
    vpp_id: str
    lat: float
    lon: float
    endurance_s: float
    speed_m_s: float
    spacing_m: float
    h_agl_m: float


@dataclass(frozen=True)
class EngineContext:
    deadline: float
    boards: tuple[BoardCamera, ...]


@dataclass(frozen=True)
class _SwathEnds:
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float


_CONTEXT: ContextVar[EngineContext | None] = ContextVar(
    "planes_fields2cover_engine",
    default=None,
)


def bind_context(ctx: EngineContext) -> Token[EngineContext | None]:
    return _CONTEXT.set(ctx)


def reset_context(token: Token[EngineContext | None]) -> None:
    _CONTEXT.reset(token)


def marked_number(record: dict[str, Any], key: str, label: str) -> float:
    """Read a catalog number stored either bare or as ``{"value": n}``."""
    raw = record.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"missing fields: {label}")
    return float(raw)


def optics(
    camera: dict[str, Any],
    gsd_cm_per_px: float,
    side_overlap: float,
) -> tuple[float, float]:
    """Swath spacing and AGL from one camera's GSD and side overlap.

    ``spacing_m = gsd_m * image_width_px * (1 - side_overlap)``.
    ``h_agl_m = gsd_m * focal_mm / (sensor_width_mm / image_width_px)``.
    """
    sensor_w = marked_number(camera, "sensor_width_mm", "sensor_width_mm")
    focal = marked_number(camera, "focal_length_mm", "focal_length_mm")
    width_px = marked_number(camera, "image_width_px", "image_width_px")
    if sensor_w <= 0 or focal <= 0 or width_px <= 0:
        raise ValueError("camera optics are not usable")
    gsd_m = float(gsd_cm_per_px) / 100.0
    spacing_m = gsd_m * width_px * (1.0 - float(side_overlap))
    h_agl_m = gsd_m * focal / (sensor_w / width_px)
    if spacing_m <= 0 or h_agl_m <= 0:
        raise ValueError("swath spacing is not positive")
    return spacing_m, h_agl_m


def plan(mission: Any) -> Any | None:
    """One strip angle, brute-force swaths, boustrophedon order, no Dubins.

    Returns ``None`` when the field yields no swaths. Raises
    ``BudgetExhausted`` when the deadline passes before a route exists.
    """
    ctx = _CONTEXT.get()
    if ctx is None:
        raise ValueError("fields2cover engine context is not set")
    if not ctx.boards:
        raise ValueError("fields2cover engine has no boards")
    for board in ctx.boards:
        if (
            not math.isfinite(board.spacing_m)
            or board.spacing_m <= 0
            or not math.isfinite(board.h_agl_m)
            or board.h_agl_m <= 0
        ):
            raise ValueError(f"camera optics are not usable for {board.uav_id}")
    _ensure_budget(False)
    origin = mission.vpps[0]
    lon0 = float(origin.lon)
    lat0 = float(origin.lat)
    angles = list(getattr(mission.params, "angles_deg", []) or [])
    auto_angle = (not angles) or (angles[0] is None) or (
        isinstance(angles[0], str) and str(angles[0]).lower() == "auto"
    )
    angle_deg = None if auto_angle else float(angles[0])
    holes = _obstacle_polygons(mission, lon0, lat0)
    polygons = _survey_polygons(mission, lon0, lat0, holes)
    if not polygons:
        return None
    groups = _groups(ctx.boards)
    routes: list[Any] = []
    durations: list[float] = []
    have_route = False
    chosen_theta: float | None = None
    for spacing_m, boards in groups:
        _ensure_budget(have_route)
        swaths, theta = _swaths(polygons, spacing_m, angle_deg)
        if chosen_theta is None and theta is not None:
            chosen_theta = float(theta)
        if not swaths:
            continue
        if time.monotonic() >= ctx.deadline and not have_route:
            raise BudgetExhausted()
        blocks = _split(swaths, len(boards))
        for board, block in zip(boards, blocks):
            _ensure_budget(have_route)
            if not block:
                continue
            aero_xy = _project(board.lon, board.lat, lon0, lat0)
            for flight_index, sortie in enumerate(
                _pack(aero_xy, block, board.endurance_s, board.speed_m_s),
                start=1,
            ):
                _ensure_budget(have_route)
                duration = _duration(aero_xy, sortie, board.speed_m_s)
                routes.append(
                    _route(
                        mission,
                        board,
                        flight_index,
                        sortie,
                        duration,
                        lon0,
                        lat0,
                        holes,
                    )
                )
                durations.append(duration)
                have_route = True
    if not routes:
        return None
    Candidate, _, _ = _models()
    used = {route.uav_id for route in routes}
    theta_out = float(chosen_theta if chosen_theta is not None else (angle_deg if angle_deg is not None else 0.0))
    return Candidate(
        theta_deg=theta_out,
        C_max_s=max(durations),
        flight_hours_s=sum(durations),
        energy_total_wh=0.0,
        n_uavs_used=len(used),
        routes=routes,
        decomposition_method="fields2cover",
    )


def _ensure_budget(have_route: bool) -> None:
    ctx = _CONTEXT.get()
    if ctx is None:
        raise ValueError("fields2cover engine context is not set")
    if time.monotonic() >= ctx.deadline and not have_route:
        raise BudgetExhausted()


def _groups(boards: tuple[BoardCamera, ...]) -> list[tuple[float, tuple[BoardCamera, ...]]]:
    grouped: dict[float, list[BoardCamera]] = {}
    for board in boards:
        key = round(board.spacing_m, 6)
        grouped.setdefault(key, []).append(board)
    return [(group[0].spacing_m, tuple(group)) for group in grouped.values()]


def _project_ring(polygon: dict[str, Any], lon0: float, lat0: float) -> list[tuple[float, float]]:
    ring = polygon["coordinates"][0]
    return [_project(float(lon), float(lat), lon0, lat0) for lon, lat in ring]


def _obstacle_polygons(mission: Any, lon0: float, lat0: float) -> list[Any]:
    from shapely.geometry import Polygon

    found = []
    for obstacle in mission.obstacles:
        poly = _clean_polygon(Polygon(_project_ring(obstacle.polygon, lon0, lat0)))
        if poly is not None:
            found.append(poly)
    return found


def _survey_polygons(
    mission: Any,
    lon0: float,
    lat0: float,
    holes: list[Any],
) -> list[Any]:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    obstacle_union = unary_union(holes) if holes else None
    found: list[Any] = []
    for area in mission.areas:
        poly = _clean_polygon(Polygon(_project_ring(area.polygon, lon0, lat0)))
        if poly is None:
            continue
        if obstacle_union is not None:
            poly = make_valid(poly.difference(obstacle_union))
        found.extend(_polygon_parts(poly))
    return found


def _clean_polygon(poly: Any) -> Any | None:
    from shapely.validation import make_valid

    if poly.is_empty:
        return None
    if not poly.is_valid:
        poly = make_valid(poly)
    parts = _polygon_parts(poly)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    from shapely.ops import unary_union

    merged = make_valid(unary_union(parts))
    parts = _polygon_parts(merged)
    if not parts:
        return None
    return max(parts, key=lambda item: item.area)


def _polygon_parts(geom: Any) -> list[Any]:
    if geom is None or geom.is_empty:
        return []
    kind = geom.geom_type
    if kind == "Polygon":
        return [geom] if geom.area >= _MIN_CELL_AREA_M2 else []
    if kind in ("MultiPolygon", "GeometryCollection"):
        found: list[Any] = []
        for part in geom.geoms:
            found.extend(_polygon_parts(part))
        return found
    return []


def _swaths(
    polygons: list[Any], spacing_m: float, angle_deg: float | None
) -> tuple[list[_SwathEnds], float | None]:
    """Generate swaths. ``angle_deg is None`` → generateBestSwaths (auto angle)."""
    f2c = _fields2cover()
    cells = f2c.Cells()
    kept = 0
    for poly in polygons:
        cell = _cell(f2c, poly)
        if cell is None:
            continue
        cells.addGeometry(cell)
        kept += 1
    if kept == 0:
        return [], None
    bf = f2c.SG_BruteForce()
    if angle_deg is None:
        obj = None
        for name in ("OBJ_NSwathModified", "OBJ_NSwath", "OBJ_SwathLength"):
            if hasattr(f2c, name):
                try:
                    obj = getattr(f2c, name)()
                    break
                except Exception:
                    continue
        if obj is None:
            raise RuntimeError("fields2cover has no OBJ_* for generateBestSwaths")
        generated = bf.generateBestSwaths(obj, float(spacing_m), cells)
    else:
        generated = bf.generateSwaths(
            math.radians(float(angle_deg)),
            float(spacing_m),
            cells,
        )
    flat = generated.flatten() if hasattr(generated, "flatten") else generated
    if int(flat.size()) == 0:
        return [], None
    ordered = f2c.RP_Boustrophedon().genSortedSwaths(flat)
    copied: list[_SwathEnds] = []
    theta: float | None = None
    for index in range(int(ordered.size())):
        swath = ordered.at(index)
        if theta is None and hasattr(swath, "getInAngle"):
            try:
                theta = math.degrees(float(swath.getInAngle())) % 180.0
            except Exception:
                theta = None
        copied.append(
            _SwathEnds(
                (float(swath.startPoint().getX()), float(swath.startPoint().getY())),
                (float(swath.endPoint().getX()), float(swath.endPoint().getY())),
                float(swath.length()),
            )
        )
    if theta is None and copied:
        x0, y0 = copied[0].start
        x1, y1 = copied[0].end
        theta = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
    if angle_deg is not None:
        theta = float(angle_deg)
    return copied, theta


def _cell(f2c: Any, poly: Any) -> Any | None:
    exterior = _linear_ring(f2c, poly.exterior.coords)
    if exterior is None:
        return None
    cell = f2c.Cell()
    cell.addRing(exterior)
    for interior in poly.interiors:
        hole = _linear_ring(f2c, interior.coords)
        if hole is not None:
            cell.addRing(hole)
    return cell


def _linear_ring(f2c: Any, coords: Any) -> Any | None:
    points: list[tuple[float, float]] = []
    for x, y, *_rest in coords:
        point = (float(x), float(y))
        if points and _hypot(point, points[-1]) < 0.01:
            continue
        points.append(point)
    if len(points) >= 2 and _hypot(points[0], points[-1]) < 0.01:
        points = points[:-1]
    if len(points) < 3:
        return None
    ring = f2c.LinearRing()
    for x, y in points:
        ring.addPoint(x, y)
    ring.addPoint(points[0][0], points[0][1])
    return ring


def _split(swaths: list[_SwathEnds], count: int) -> list[list[_SwathEnds]]:
    if count <= 0:
        return []
    blocks: list[list[_SwathEnds]] = [[] for _ in range(count)]
    base, extra = divmod(len(swaths), count)
    cursor = 0
    for index in range(count):
        take = base + (1 if index < extra else 0)
        blocks[index] = swaths[cursor : cursor + take]
        cursor += take
    return blocks


def _pack(
    aero_xy: tuple[float, float],
    swaths: list[_SwathEnds],
    endurance_s: float,
    speed_m_s: float,
) -> list[list[_SwathEnds]]:
    sorties: list[list[_SwathEnds]] = []
    current: list[_SwathEnds] = []
    for swath in swaths:
        trial = [*current, swath]
        if current and _duration(aero_xy, trial, speed_m_s) > endurance_s:
            sorties.append(current)
            current = [swath]
        else:
            current = trial
    if current:
        sorties.append(current)
    return sorties


def _duration(
    aero_xy: tuple[float, float],
    swaths: list[_SwathEnds],
    speed_m_s: float,
) -> float:
    if speed_m_s <= 0:
        raise ValueError("airspeed_m_s is not positive")
    return _length(aero_xy, swaths) / speed_m_s


def _length(aero_xy: tuple[float, float], swaths: list[_SwathEnds]) -> float:
    cursor = aero_xy
    total = 0.0
    for swath in swaths:
        total += _hypot(cursor, swath.start)
        total += swath.length_m
        cursor = swath.end
    total += _hypot(cursor, aero_xy)
    return total


def _route(
    mission: Any,
    board: BoardCamera,
    flight_index: int,
    sortie: list[_SwathEnds],
    duration_s: float,
    lon0: float,
    lat0: float,
    holes: list[Any],
) -> Any:
    _, Point, Route = _models()
    ground = _ground(mission.dem, board.lat, board.lon)
    aero_xy = _project(board.lon, board.lat, lon0, lat0)
    # "swath" points are sampled. "link" points copy a neighbouring sample so a
    # hole bypass does not add terrain reads away from the swath ends.
    samples: list[tuple[str, tuple[float, float]]] = [("ground", aero_xy)]
    cursor = aero_xy
    for swath in sortie:
        samples.extend(("link", point) for point in _avoid(cursor, swath.start, holes)[1:-1])
        samples.append(("swath", swath.start))
        samples.append(("swath", swath.end))
        cursor = swath.end
    samples.extend(("link", point) for point in _avoid(cursor, aero_xy, holes)[1:-1])
    samples.append(("ground", aero_xy))
    altitudes: list[float | None] = []
    for kind, (x, y) in samples:
        if kind == "ground":
            altitudes.append(ground)
        elif kind == "swath":
            lat, lon = _unproject(x, y, lon0, lat0)
            altitudes.append(_ground(mission.dem, lat, lon) + board.h_agl_m)
        else:
            altitudes.append(None)
    upcoming = ground
    for index in range(len(altitudes) - 1, -1, -1):
        if altitudes[index] is None:
            altitudes[index] = upcoming
        else:
            upcoming = altitudes[index]
    waypoints = []
    for (kind, (x, y)), alt in zip(samples, altitudes):
        del kind
        if (x, y) == aero_xy and not waypoints:
            lat, lon = board.lat, board.lon
        elif (x, y) == aero_xy and len(waypoints) == len(samples) - 1:
            lat, lon = board.lat, board.lon
        else:
            lat, lon = _unproject(x, y, lon0, lat0)
        waypoints.append(Point(lat=lat, lon=lon, alt_m=float(alt)))
    return Route(
        uav_id=board.uav_id,
        flight_index=flight_index,
        vpp_id=board.vpp_id,
        T_total_s=duration_s,
        waypoints=waypoints,
    )


def _avoid(
    start: tuple[float, float],
    end: tuple[float, float],
    holes: list[Any],
) -> list[tuple[float, float]]:
    """Straight link, or a short path just outside a constraint it would cross."""
    path = [start, end]
    if not holes:
        return path
    for _ in range(4):
        changed = False
        expanded = [path[0]]
        for point in path[1:]:
            previous = expanded[-1]
            blocking = next((hole for hole in holes if _hits(previous, point, hole)), None)
            if blocking is None:
                expanded.append(point)
                continue
            detour = _detour(previous, point, blocking)
            expanded.extend(detour[1:])
            changed = True
        path = expanded
        if not changed:
            break
    return path


def _detour(
    start: tuple[float, float],
    end: tuple[float, float],
    hole: Any,
) -> list[tuple[float, float]]:
    outset = hole.buffer(2.0)
    if outset.is_empty or outset.exterior is None:
        return [start, end]
    ring = [
        (float(x), float(y))
        for x, y, *_rest in list(outset.exterior.coords)[:-1]
    ]
    count = len(ring)
    best: tuple[float, list[tuple[float, float]]] | None = None
    for origin in range(count):
        for length in range(1, count):
            chain = [ring[(origin + step) % count] for step in range(length)]
            path = [start, *chain, end]
            if any(_hits(path[index], path[index + 1], hole) for index in range(len(path) - 1)):
                continue
            cost = sum(_hypot(path[index], path[index + 1]) for index in range(len(path) - 1))
            if best is None or cost < best[0]:
                best = (cost, path)
    if best is None:
        return [start, end]
    return best[1]


def _hits(start: tuple[float, float], end: tuple[float, float], hole: Any) -> bool:
    from shapely.geometry import LineString

    if _hypot(start, end) < 0.05:
        return False
    line = LineString([start, end])
    return line.intersection(hole).length > 0.5


def _ground(dem: Any, lat: float, lon: float) -> float:
    height = float(dem.h(lat, lon))
    if not math.isfinite(height):
        raise ValueError("terrain sample is not finite")
    return height


def _project(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    scale = _lon_scale(lat0)
    return ((lon - lon0) * _LON_M_PER_DEG * scale, (lat - lat0) * _LAT_M_PER_DEG)


def _unproject(x: float, y: float, lon0: float, lat0: float) -> tuple[float, float]:
    scale = _lon_scale(lat0)
    return (lat0 + y / _LAT_M_PER_DEG, lon0 + x / (_LON_M_PER_DEG * scale))


def _lon_scale(lat0: float) -> float:
    scale = math.cos(math.radians(lat0))
    if abs(scale) < 1e-6:
        return 1e-6 if scale >= 0 else -1e-6
    return scale


def _hypot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _fields2cover() -> Any:
    import importlib.metadata as metadata
    import fields2cover as f2c

    installed = metadata.version("fields2cover")
    if installed != FIELDS2COVER_VERSION:
        raise ValueError(
            f"fields2cover {installed} does not match the pinned import {FIELDS2COVER_VERSION}"
        )
    return f2c


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    alt_m: float


@dataclass(frozen=True)
class Route:
    uav_id: str
    flight_index: int
    vpp_id: str
    T_total_s: float
    waypoints: list


@dataclass(frozen=True)
class Candidate:
    theta_deg: float
    C_max_s: float
    flight_hours_s: float
    energy_total_wh: float
    n_uavs_used: int
    routes: list
    decomposition_method: str


def _models() -> tuple[Any, Any, Any]:
    """Local stubs — NEVER import planner.models / mvp sitecustomize."""
    return Candidate, Point, Route
