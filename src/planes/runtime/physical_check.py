"""Name physical findings on a finished plan.

This module reads the plan and the input. It does not build a route, call
the solver, or change waypoint coordinates. Flight level uses a team
approximation (1 FL = 100 ft, 1 ft = 0.3048 m). That approximation is not a
customer requirement. AGL and AMSL numbers are compared with the waypoint
``alt_m`` already stored on the plan.
"""

from __future__ import annotations

import math
import re
from typing import Any


_LAT_M_PER_DEG = 110540.0
_LON_M_PER_DEG = 111320.0
_FT_TO_M = 0.3048
_FL_TO_M = 100.0 * _FT_TO_M

_TEXT = {
    "PHYS-ENDURANCE": "Вылет длиннее выносливости борта",
    "PHYS-VPP-INSIDE": "Старт внутри зоны, активной на высоте маршрута",
    "PHYS-AIRSPACE": "Маршрут входит в зону, активную на высоте сегмента",
    "PHYS-DEM": "Рельеф отсутствует или нечисловой",
    "PHYS-TIMEOUT": "Расчёт остановлен по лимиту времени",
    "PHYS-NO-PLAN": "Допустимого плана нет",
}
_UNKNOWN_VPP = (
    "PHYS-VPP-INSIDE: Неразобранный текст высоты — консервативный отказ, "
    "старт уже внутри зоны"
)
_UNKNOWN_AIR = (
    "PHYS-AIRSPACE: Неразобранный текст высоты — консервативный отказ, "
    "маршрут уже входит в зону"
)
_TIME_LIMIT = "solver stopped at the time limit"
_DEM_MARKERS = (
    "terrain sample is not finite",
    "not a usable GeoTIFF",
    "not a TIFF",
    "no finite surface",
    "OPENTOPOGRAPHY",
    "Downloaded raster",
    "terrain raster",
)
_FL = re.compile(r"^fl\s*(\d+)$", re.IGNORECASE)
_FROM_TO = re.compile(r"^от\s+(.+?)\s+до\s+(.+)$", re.IGNORECASE)
_METRES = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*(?:м|m)?\s*(amsl|agl|gnd|м|m)?$",
    re.IGNORECASE,
)
_SURFACE = {"gnd", "земли", "поверхность", "0"}
_ALWAYS = {"all", "все", "все высоты"}


def code_line(code: str) -> str:
    return f"{code}: {_TEXT[code]}"


def limitation_lines(
    *,
    plan: dict[str, Any] | None,
    scenario: dict[str, Any] | None,
    limitations: tuple[str, ...] | list[str] | None,
    outcome: str,
) -> tuple[str, ...]:
    """Return new limitation lines. The plan object is not modified."""
    notes = tuple(item for item in (limitations or ()) if isinstance(item, str))
    scenario = scenario if isinstance(scenario, dict) else {}
    found: list[str] = []
    dem = _dem(plan, notes)
    if dem:
        found.append(code_line("PHYS-DEM"))
    else:
        if _endurance(plan, scenario):
            found.append(code_line("PHYS-ENDURANCE"))
        vpp_unknown, vpp = _vpp_inside(plan)
        air_unknown, air = _airspace(plan)
        if vpp:
            found.append(_UNKNOWN_VPP if vpp_unknown else code_line("PHYS-VPP-INSIDE"))
        if air:
            found.append(_UNKNOWN_AIR if air_unknown else code_line("PHYS-AIRSPACE"))
    if _timeout(outcome, notes):
        found.append(code_line("PHYS-TIMEOUT"))
    if _no_plan(outcome) and not found:
        found.append(code_line("PHYS-NO-PLAN"))
    fresh = []
    for line in found:
        code = line.split(":", 1)[0]
        if any(code in note for note in (*notes, *fresh)):
            continue
        fresh.append(line)
    return tuple(fresh)


def annotate_result(result: Any, scenario: dict[str, Any] | None) -> Any:
    """Append codes to an existing solver result. The mission plan stays as it was."""
    from planes.runtime.solver import Infeasible, Solution, TimedOut

    if isinstance(result, Solution):
        outcome = "feasible"
        plan = result.mission_plan if isinstance(result.mission_plan, dict) else None
    elif isinstance(result, Infeasible):
        outcome = "infeasible"
        plan = None
    elif isinstance(result, TimedOut):
        outcome = "timed_out"
        plan = None
    else:
        return result
    extra = limitation_lines(
        plan=plan,
        scenario=scenario,
        limitations=result.limitations,
        outcome=outcome,
    )
    if not extra:
        return result
    merged = tuple(result.limitations) + extra
    if isinstance(result, Solution):
        return Solution(
            mission_plan=result.mission_plan,
            method=result.method,
            objective_value=result.objective_value,
            limitations=merged,
        )
    if isinstance(result, Infeasible):
        return Infeasible(merged)
    return TimedOut(merged)


def _dem(plan: dict[str, Any] | None, notes: tuple[str, ...]) -> bool:
    if any(marker in note for note in notes for marker in _DEM_MARKERS):
        return True
    if not isinstance(plan, dict):
        return False
    for route in plan.get("routes") or []:
        if not isinstance(route, dict):
            continue
        for point in route.get("waypoints") or []:
            if not isinstance(point, dict) or not _finite(point.get("alt_m")):
                return True
    return False


def _timeout(outcome: str, notes: tuple[str, ...]) -> bool:
    if outcome == "timed_out":
        return True
    return any(_TIME_LIMIT in note for note in notes)


def _no_plan(outcome: str) -> bool:
    return outcome == "infeasible"


def _endurance(plan: dict[str, Any] | None, scenario: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    limits = _board_limits(scenario)
    if not limits:
        return False
    for route in plan.get("routes") or []:
        if not isinstance(route, dict):
            continue
        bound = limits.get(route.get("uav_id"))
        if bound is None:
            continue
        endurance_s, speed_m_s = bound
        if endurance_s <= 0 or speed_m_s <= 0:
            continue
        if _leg_seconds(route.get("waypoints") or [], speed_m_s) > endurance_s:
            return True
    return False


def _board_limits(scenario: dict[str, Any]) -> dict[str, tuple[float, float]]:
    boards = scenario.get("boards")
    if not isinstance(boards, list) or not boards:
        return {}
    from planes.runtime.enumeration.outer import load_catalog

    catalog = load_catalog()
    models = {
        item["id"]: item
        for item in catalog.get("uav_models", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    found: dict[str, tuple[float, float]] = {}
    for board in boards:
        if not isinstance(board, dict):
            continue
        model = models.get(board.get("model_id"))
        if model is None:
            continue
        endurance = _marked(model.get("flight_time_s"))
        speed = _marked(model.get("airspeed_m_s"))
        if endurance is None or speed is None:
            continue
        board_id = board.get("id")
        count = board.get("count")
        if not isinstance(board_id, str) or isinstance(count, bool) or not isinstance(count, int):
            continue
        ids = [board_id] if count == 1 else [f"{board_id}-{index + 1}" for index in range(count)]
        for uav_id in ids:
            found[uav_id] = (endurance, speed)
    return found


def _marked(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _leg_seconds(waypoints: list[Any], speed_m_s: float) -> float:
    total = 0.0
    previous: tuple[float, float] | None = None
    for point in waypoints:
        if not isinstance(point, dict) or not _finite(point.get("lon")) or not _finite(point.get("lat")):
            continue
        current = (float(point["lon"]), float(point["lat"]))
        if previous is not None:
            total += _metres(previous, current) / speed_m_s
        previous = current
    return total


def _metres(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = start
    lon2, lat2 = end
    scale = math.cos(math.radians((lat1 + lat2) / 2.0))
    east = (lon2 - lon1) * _LON_M_PER_DEG * scale
    north = (lat2 - lat1) * _LAT_M_PER_DEG
    return math.hypot(east, north)


def _vpp_inside(plan: dict[str, Any] | None) -> tuple[bool, bool]:
    unknown = False
    hit = False
    for route, zones in _routes(plan):
        points = route.get("waypoints") or []
        if not points:
            continue
        start = points[0]
        if not _finite(start.get("alt_m")):
            continue
        altitude = float(start["alt_m"])
        for zone in zones:
            if not _active(zone["parsed"], altitude, altitude):
                continue
            if not _covers(zone["polygon"], float(start["lon"]), float(start["lat"])):
                continue
            hit = True
            unknown = unknown or bool(zone["parsed"]["unknown"])
    return unknown, hit


def _airspace(plan: dict[str, Any] | None) -> tuple[bool, bool]:
    unknown = False
    hit = False
    for route, zones in _routes(plan):
        points = [point for point in (route.get("waypoints") or []) if isinstance(point, dict)]
        if len(points) < 2:
            continue
        start = points[0]
        for zone in zones:
            start_inside = False
            if _finite(start.get("alt_m")) and _active(
                zone["parsed"], float(start["alt_m"]), float(start["alt_m"])
            ):
                start_inside = _covers(zone["polygon"], float(start["lon"]), float(start["lat"]))
            entered = _route_enters(points, zone, skip_departure=start_inside)
            if not entered:
                continue
            hit = True
            unknown = unknown or bool(zone["parsed"]["unknown"])
    return unknown, hit


def _route_enters(points: list[dict[str, Any]], zone: dict[str, Any], *, skip_departure: bool) -> bool:
    polygon = zone["polygon"]
    parsed = zone["parsed"]
    for index, point in enumerate(points):
        if index == 0 or not _finite(point.get("alt_m")) or not _finite(point.get("lon")):
            continue
        altitude = float(point["alt_m"])
        if _active(parsed, altitude, altitude) and _covers(polygon, float(point["lon"]), float(point["lat"])):
            return True
    pairs = list(enumerate(zip(points, points[1:])))
    for index, (start, end) in pairs:
        if skip_departure and index == 0:
            continue
        if not all(_finite(point.get("alt_m")) and _finite(point.get("lon")) and _finite(point.get("lat")) for point in (start, end)):
            continue
        low = min(float(start["alt_m"]), float(end["alt_m"]))
        high = max(float(start["alt_m"]), float(end["alt_m"]))
        if not _active(parsed, low, high):
            continue
        if _segment_hits(polygon, start, end):
            return True
    return False


def _routes(plan: dict[str, Any] | None) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    if not isinstance(plan, dict):
        return []
    zones = _zones(plan.get("constraint_polygons"))
    routes = []
    for route in plan.get("routes") or []:
        if isinstance(route, dict):
            routes.append((route, zones))
    return routes


def _zones(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    from shapely.geometry import Polygon

    zones = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("ring"), list):
            continue
        coordinates = []
        for point in item["ring"]:
            if (
                isinstance(point, (list, tuple))
                and len(point) >= 2
                and _finite(point[0])
                and _finite(point[1])
            ):
                coordinates.append((float(point[0]), float(point[1])))
        if len(coordinates) < 3:
            continue
        try:
            polygon = Polygon(coordinates)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
        except (TypeError, ValueError):
            continue
        zones.append(
            {
                "polygon": polygon,
                "parsed": _parse_altitude(item.get("altitudes_text")),
            }
        )
    return zones


def _covers(polygon: Any, lon: float, lat: float) -> bool:
    from shapely.geometry import Point

    return bool(polygon.covers(Point(lon, lat)))


def _segment_hits(polygon: Any, start: dict[str, Any], end: dict[str, Any]) -> bool:
    from shapely.geometry import LineString

    line = LineString(
        [(float(start["lon"]), float(start["lat"])), (float(end["lon"]), float(end["lat"]))]
    )
    return bool(line.intersects(polygon))


def _active(parsed: dict[str, Any], low: float, high: float) -> bool:
    if parsed["unknown"] or parsed["always"]:
        return True
    floor = parsed["lo"] if parsed["lo"] is not None else float("-inf")
    ceiling = parsed["hi"] if parsed["hi"] is not None else float("inf")
    return not (high < floor or low > ceiling)


def _parse_altitude(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {"unknown": False, "always": True, "lo": None, "hi": None}
    folded = " ".join(raw.replace("\xa0", " ").split())
    if folded.casefold() in _ALWAYS:
        return {"unknown": False, "always": True, "lo": None, "hi": None}
    span = _FROM_TO.fullmatch(folded)
    if span:
        lower = _bound(span.group(1))
        upper = _bound(span.group(2))
        if lower is None or upper is None:
            return {"unknown": True, "always": False, "lo": None, "hi": None}
        lo, hi = sorted((lower, upper))
        return {"unknown": False, "always": False, "lo": lo, "hi": hi}
    single = _bound(folded)
    if single is None:
        return {"unknown": True, "always": False, "lo": None, "hi": None}
    return {"unknown": False, "always": False, "lo": single, "hi": None}


def _bound(text: str) -> float | None:
    folded = " ".join(text.replace("\xa0", " ").split()).casefold()
    if folded in _SURFACE:
        return 0.0
    compact = folded.replace(" ", "")
    flight = _FL.fullmatch(compact) or _FL.fullmatch(folded)
    if flight is not None:
        return int(flight.group(1)) * _FL_TO_M
    metres = _METRES.fullmatch(folded)
    if metres is None:
        return None
    return float(metres.group(1).replace(",", "."))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
