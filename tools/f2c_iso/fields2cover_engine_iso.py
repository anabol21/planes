"""Isolated copy of planes.runtime.fields2cover_engine for F2C embed venv.

COPY only — listener /opt/planes is untouched. Local Candidate/Point/Route
stubs replace planner.models so mvp_optimizator/src (and sitecustomize.py)
is NEVER added to sys.path. Run under .venv-f2c-embed with clean PYTHONPATH.
Empty angles → SG_BruteForce.generateBestSwaths. This is pack/split F2C,
not full mvp LNS/assignment.
"""

from __future__ import annotations

import math
import sys
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ISO_SRC = Path(__file__).resolve().parent / "iso_src"
if str(_ISO_SRC) not in sys.path:
    sys.path.insert(0, str(_ISO_SRC))

from wave_b import (  # noqa: E402
    CoverageInfeasible,
    Pad as WavePad,
    PackedSortie,
    Swath as WaveSwath,
    apply_recharge_timeline,
    makespan_s,
    pack_board,
    recharge_gap_s,
    resolve_separation,
    total_flight_time_s,
)

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
    recharge_time_s: float = 0.0


@dataclass(frozen=True)
class EngineContext:
    deadline: float
    boards: tuple[BoardCamera, ...]
    pads: tuple[Any, ...] = ()
    allow_recharge: bool = True
    allow_foreign_landing: bool = True
    allow_foreign_takeoff: bool = False
    min_separation_m: float = 50.0
    time_window_s: float = 0.0


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
    packed: list[PackedSortie] = []
    pack_notes: list[str] = []
    uncovered_total = 0
    have_route = False
    chosen_theta: float | None = None
    pads, pad_geo = _wave_pads(ctx, lon0, lat0)
    board_by_id = {board.uav_id: board for board in ctx.boards}
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
            result = pack_board(
                uav_id=board.uav_id,
                swaths=[
                    WaveSwath(item.start, item.end, item.length_m) for item in block
                ],
                pads=pads,
                home_pad_id=board.vpp_id,
                endurance_s=board.endurance_s,
                speed_m_s=board.speed_m_s,
                allow_foreign_landing=ctx.allow_foreign_landing,
                allow_foreign_takeoff=ctx.allow_foreign_takeoff,
                allow_recharge=ctx.allow_recharge,
            )
            pack_notes.extend(result.limitations)
            uncovered_total += len(result.uncovered)
            packed.extend(result.sorties)
            have_route = have_route or bool(result.sorties)
    if uncovered_total:
        if ctx.allow_recharge:
            reason = (
                f"uncovered swaths={uncovered_total}: a swath exceeds endurance "
                "even with recharge and best pads"
            )
        else:
            reason = (
                f"allow_recharge=false: uncovered swaths={uncovered_total} "
                "(coverage needs more than one sortie under endurance)"
            )
        raise CoverageInfeasible(
            reason,
            uncovered=uncovered_total,
            limitations=(reason, *pack_notes),
        )
    if not packed:
        return None
    recharge_by_uav = {board.uav_id: board.recharge_time_s for board in ctx.boards}
    apply_recharge_timeline(packed, recharge_by_uav)
    speed_by_uav = {board.uav_id: board.speed_m_s for board in ctx.boards}
    packed, n_conflicts, sep_delay, sep_notes = resolve_separation(
        packed,
        speed_by_uav,
        ctx.min_separation_m,
        ctx.time_window_s,
    )
    routes: list[Any] = []
    flight_index_by_uav: dict[str, int] = {}
    for sortie in packed:
        _ensure_budget(True)
        board = board_by_id[sortie.uav_id]
        flight_index_by_uav[sortie.uav_id] = flight_index_by_uav.get(sortie.uav_id, 0) + 1
        takeoff = _pad_geo(pad_geo, sortie.takeoff_pad_id, board)
        landing = _pad_geo(pad_geo, sortie.landing_pad_id, board)
        routes.append(
            _route(
                mission,
                board,
                flight_index_by_uav[sortie.uav_id],
                [_SwathEnds(item.start, item.end, item.length_m) for item in sortie.swaths],
                float(sortie.flight_time_s),
                lon0,
                lat0,
                holes,
                takeoff=takeoff,
                landing=landing,
                start_time_s=float(sortie.start_time_s),
                recharge_before_s=float(sortie.recharge_before_s),
            )
        )
    Candidate, _, _ = _models()
    used = {route.uav_id for route in routes}
    theta_out = float(chosen_theta if chosen_theta is not None else (angle_deg if angle_deg is not None else 0.0))
    extra = (
        *pack_notes,
        *sep_notes,
        f"wave_b conflicts_seen={n_conflicts} separation_delay_s={sep_delay:.1f}",
        "wave_b: mission_time_s is Cmax including recharge gaps and separation delays; "
        "total_flight_time_s is airborne time only",
    )
    return Candidate(
        theta_deg=theta_out,
        C_max_s=makespan_s(packed),
        flight_hours_s=total_flight_time_s(packed),
        energy_total_wh=0.0,
        n_uavs_used=len(used),
        routes=routes,
        decomposition_method="fields2cover",
        recharge_gap_s=recharge_gap_s(packed),
        separation_delay_s=float(sep_delay),
        uncovered_swath_count=0,
        extra_limitations=extra,
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


def _wave_pads(
    ctx: EngineContext,
    lon0: float,
    lat0: float,
) -> tuple[list[WavePad], dict[str, tuple[float, float, float]]]:
    """Return local-metre pads and ``id -> (lat, lon, unused)`` geo lookup."""
    raw = list(ctx.pads) if ctx.pads else []
    if not raw:
        seen: dict[str, BoardCamera] = {}
        for board in ctx.boards:
            seen.setdefault(board.vpp_id, board)
        raw = [
            type("Pad", (), {"id": board.vpp_id, "lat": board.lat, "lon": board.lon})()
            for board in seen.values()
        ]
    pads: list[WavePad] = []
    geo: dict[str, tuple[float, float, float]] = {}
    for item in raw:
        pad_id = str(item.id)
        lat = float(item.lat)
        lon = float(item.lon)
        pads.append(WavePad(pad_id, _project(lon, lat, lon0, lat0)))
        geo[pad_id] = (lat, lon, 0.0)
    return pads, geo


def _pad_geo(
    geo: dict[str, tuple[float, float, float]],
    pad_id: str,
    board: BoardCamera,
) -> Any:
    if pad_id in geo:
        lat, lon, _ = geo[pad_id]
        return type("PadGeo", (), {"id": pad_id, "lat": lat, "lon": lon})()
    return type("PadGeo", (), {"id": board.vpp_id, "lat": board.lat, "lon": board.lon})()


def _route(
    mission: Any,
    board: BoardCamera,
    flight_index: int,
    sortie: list[_SwathEnds],
    duration_s: float,
    lon0: float,
    lat0: float,
    holes: list[Any],
    takeoff: Any | None = None,
    landing: Any | None = None,
    start_time_s: float = 0.0,
    recharge_before_s: float = 0.0,
) -> Any:
    _, Point, Route = _models()
    takeoff = takeoff or type("PadGeo", (), {"id": board.vpp_id, "lat": board.lat, "lon": board.lon})()
    landing = landing or takeoff
    takeoff_ground = _ground(mission.dem, float(takeoff.lat), float(takeoff.lon))
    landing_ground = _ground(mission.dem, float(landing.lat), float(landing.lon))
    takeoff_xy = _project(float(takeoff.lon), float(takeoff.lat), lon0, lat0)
    landing_xy = _project(float(landing.lon), float(landing.lat), lon0, lat0)
    # "swath" points are sampled. "link" points copy a neighbouring sample so a
    # hole bypass does not add terrain reads away from the swath ends.
    samples: list[tuple[str, tuple[float, float]]] = [("ground", takeoff_xy)]
    cursor = takeoff_xy
    for swath in sortie:
        samples.extend(("link", point) for point in _avoid(cursor, swath.start, holes)[1:-1])
        samples.append(("swath", swath.start))
        samples.append(("swath", swath.end))
        cursor = swath.end
    samples.extend(("link", point) for point in _avoid(cursor, landing_xy, holes)[1:-1])
    samples.append(("ground", landing_xy))
    altitudes: list[float | None] = []
    for kind, (x, y) in samples:
        if kind == "ground" and (x, y) == takeoff_xy and not altitudes:
            altitudes.append(takeoff_ground)
        elif kind == "ground":
            altitudes.append(landing_ground)
        elif kind == "swath":
            lat, lon = _unproject(x, y, lon0, lat0)
            altitudes.append(_ground(mission.dem, lat, lon) + board.h_agl_m)
        else:
            altitudes.append(None)
    upcoming = landing_ground
    for index in range(len(altitudes) - 1, -1, -1):
        if altitudes[index] is None:
            altitudes[index] = upcoming
        else:
            upcoming = altitudes[index]
    waypoints = []
    for (kind, (x, y)), alt in zip(samples, altitudes):
        del kind
        if (x, y) == takeoff_xy and not waypoints:
            lat, lon = float(takeoff.lat), float(takeoff.lon)
        elif (x, y) == landing_xy and len(waypoints) == len(samples) - 1:
            lat, lon = float(landing.lat), float(landing.lon)
        else:
            lat, lon = _unproject(x, y, lon0, lat0)
        waypoints.append(Point(lat=lat, lon=lon, alt_m=float(alt)))
    return Route(
        uav_id=board.uav_id,
        flight_index=flight_index,
        vpp_id=str(takeoff.id),
        T_total_s=duration_s,
        waypoints=waypoints,
        takeoff_vpp_id=str(takeoff.id),
        landing_vpp_id=str(landing.id),
        start_time_s=float(start_time_s),
        recharge_before_s=float(recharge_before_s),
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
    takeoff_vpp_id: str = ""
    landing_vpp_id: str = ""
    start_time_s: float = 0.0
    recharge_before_s: float = 0.0


@dataclass(frozen=True)
class Candidate:
    theta_deg: float
    C_max_s: float
    flight_hours_s: float
    energy_total_wh: float
    n_uavs_used: int
    routes: list
    decomposition_method: str
    recharge_gap_s: float = 0.0
    separation_delay_s: float = 0.0
    uncovered_swath_count: int = 0
    extra_limitations: tuple[str, ...] = ()


def _models() -> tuple[Any, Any, Any]:
    """Local stubs — NEVER import planner.models / mvp sitecustomize."""
    return Candidate, Point, Route
