"""Envelope adapter for the copied geo core.

An envelope with aerodromes and boards becomes one ``MissionInput`` and one
call of ``planner.solver.pipeline``. The one-card ``takeoff`` + ``uav`` path
stays on gibrid-optimizer. This module does not edit the planner body.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from planes.integration.kml.constraints import (
    ConstraintPolygon,
    parse_constraint_polygons,
    parse_survey_polygon,
)
from planes.integration.terrain.opentopography import (
    TerrainAcquisitionError,
    acquire_terrain_for_area,
)
from planes.runtime.enumeration.outer import load_catalog
from planes.runtime.logs import record
from planes.runtime.solver import Problem


_CORE_SRC = (
    Path(__file__).resolve().parents[1]
    / "model"
    / "itog_model"
    / "mvp_optimizator"
    / "src"
)
_MODEL_IDS = {
    "geoscan-gemini": "gemini",
    "geoscan-201": "geoscan201",
    "geoscan-801": "geoscan801",
}
# Fleet camera ids that ``data/data.json`` search_index names, including the
# two UMC focals and the two 801 visible focals, which share one core id each.
_CAMERA_IDS = {
    "geoscan-pf1b": "pf1b",
    "sony-umc-r10c-16": "umc-r10c",
    "sony-umc-r10c-20": "umc-r10c",
    "geoscan-pollux": "pollux",
    "riebo-r4": "riebo-r4",
    "riebo-r6": "riebo-r6",
    "sony-dsc-rx1rm2": "rx1rm2",
    "sony-dsc-rx1rm3": "rx1rm3",
    "sony-zv-e10": "zv-e10",
    "geoscan-801-visible-4-35": "801-visible",
    "geoscan-801-visible-16": "801-visible",
    "geoscan-801-thermal": "801-thermal",
}
_SURVEY_TYPES = {
    "RGB": "visible",
    "visible": "visible",
    "multispectral": "multispectral",
    "infrared": "thermal",
    "thermal": "thermal",
}
_TIME_LIMIT = "solver stopped at the time limit"
_NOT_GLOBALLY_OPTIMAL = "heuristic result is not globally optimal"
_NO_SPECTRUM = "no camera covers required spectrum"
_FLAT_TERRAIN = "terrain raster is not a usable GeoTIFF; refusing flat terrain"


def solve_envelope(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Parse both KML texts, cache COP30, and call the geo-core pipeline."""
    from planes.runtime.solver import Infeasible, Solution, TimedOut

    if time.monotonic() >= deadline:
        return TimedOut((_TIME_LIMIT,))
    scenario = problem.scenario
    if not isinstance(scenario, dict):
        raise ValueError("missing fields: scenario")
    survey_ring = parse_survey_polygon(_text(scenario.get("survey_kml"), "survey_kml"))
    constraints = parse_constraint_polygons(_optional_text(scenario.get("constraints_kml")))
    dem_path = _acquire_dem(survey_ring)
    dem = _load_geotiff(dem_path)
    mission, notes = _mission(
        scenario,
        survey_ring=survey_ring,
        constraints=constraints,
        dem_path=dem_path,
        dem=dem,
    )
    if mission is None:
        lines = tuple(notes) or (_NO_SPECTRUM,)
        _log(problem.job_id, lines)
        return Infeasible(lines)
    if time.monotonic() >= deadline:
        lines = (_TIME_LIMIT, *notes)
        _log(problem.job_id, lines)
        return TimedOut(lines)
    candidate = _run_pipeline(mission)
    if candidate is None:
        lines = ("No valid candidates found", *notes)
        _log(problem.job_id, lines)
        return Infeasible(lines)
    plan = _plan(candidate, mission, str(dem_path), constraints)
    criterion = mission.params.optimization_criterion.value
    if criterion == "min_time":
        objective_value = float(candidate.C_max_s)
    else:
        objective_value = float(candidate.flight_hours_s)
    lines = (
        _NOT_GLOBALLY_OPTIMAL,
        "constraint altitude text is copied and not interpreted; polygons are obstacles",
        f"dem_file: {dem_path}",
        *notes,
    )
    _log(problem.job_id, lines)
    return Solution(
        mission_plan=plan,
        method="pipeline",
        objective_value=objective_value,
        limitations=lines,
    )


def _acquire_dem(ring: list[list[float]]) -> Path:
    geometry = {"type": "Polygon", "coordinates": [ring]}
    try:
        return Path(
            acquire_terrain_for_area(geometry, survey_crs="EPSG:4326")
        ).resolve()
    except TerrainAcquisitionError as exc:
        raise ValueError(str(exc)) from exc


def _load_geotiff(path: Path) -> Any:
    load_dem = _core_symbols()["load_dem"]
    dem = load_dem(path)
    if type(dem).__name__ == "FlatDEM" or dem.is_empty():
        raise ValueError(_FLAT_TERRAIN)
    return dem


def _mission(
    scenario: dict[str, Any],
    *,
    survey_ring: list[list[float]],
    constraints: list[ConstraintPolygon],
    dem_path: Path,
    dem: Any,
) -> tuple[Any | None, list[str]]:
    symbols = _core_symbols()
    catalog = symbols["get_default_catalog"]()
    fleet = load_catalog()
    models = _index(fleet.get("uav_models"), "uav_models")
    cameras = _index(fleet.get("cameras"), "cameras")
    edges = _edges(fleet, models, cameras)
    spectrum = _text(scenario.get("required_spectrum"), "required_spectrum")
    survey_type = _SURVEY_TYPES.get(spectrum)
    if survey_type is None:
        raise ValueError(
            f"survey type {spectrum} is not accepted by the geo core "
            "(visible, multispectral, thermal)"
        )
    criterion_name = _text(scenario.get("criterion"), "criterion")
    if criterion_name not in ("min_time", "min_flight_hours"):
        raise ValueError("missing fields: criterion")
    aerodromes = _aerodromes(scenario.get("aerodromes"))
    boards = _boards(scenario.get("boards"), aerodromes)
    notes: list[str] = []
    admitted: list[tuple[dict[str, Any], str, str]] = []
    for board in boards:
        model_id = board["model_id"]
        camera_id = board["camera_id"]
        if (model_id, camera_id) not in edges:
            raise ValueError(f"camera {camera_id} is not compatible with model {model_id}")
        spectra = _spectra(cameras[camera_id])
        if spectrum not in spectra:
            listed = ", ".join(spectra)
            notes.append(
                f"spectrum mismatch model {model_id} camera {camera_id}: "
                f"required {spectrum}, camera spectra {listed}"
            )
            continue
        core_model = _translate_model(model_id, catalog)
        core_camera = _translate_camera(camera_id, catalog)
        admitted.append((board, core_model, core_camera))
    if not admitted:
        if notes:
            notes.insert(0, _NO_SPECTRUM)
        else:
            notes.append("no runnable board")
        return None, notes

    Area = symbols["Area"]
    Obstacle = symbols["Obstacle"]
    SurveyType = symbols["SurveyType"]
    UAVConfig = symbols["UAVConfig"]
    VPP = symbols["VPP"]
    MissionInput = symbols["MissionInput"]
    area = Area(
        id="survey",
        name="survey",
        survey_type=SurveyType(survey_type),
        polygon={"type": "Polygon", "coordinates": [survey_ring]},
    )
    obstacles = [
        Obstacle(
            id=f"constraint-{index + 1}",
            name=polygon.name or "",
            height_m=0.0,
            polygon={
                "type": "Polygon",
                "coordinates": [[[lon, lat] for lon, lat in polygon.ring]],
            },
        )
        for index, polygon in enumerate(constraints)
    ]
    uavs = []
    by_vpp: dict[str, list[str]] = {item["id"]: [] for item in aerodromes}
    cameras_by_vpp: dict[str, list[str]] = {item["id"]: [] for item in aerodromes}
    for board, core_model, core_camera in admitted:
        count = board["count"]
        ids = [board["id"]] if count == 1 else [f"{board['id']}-{index + 1}" for index in range(count)]
        for uav_id in ids:
            uavs.append(
                UAVConfig(
                    id=uav_id,
                    model=core_model,
                    camera_id=core_camera,
                    vpp_id=board["aerodrome_id"],
                )
            )
            by_vpp[board["aerodrome_id"]].append(uav_id)
            if core_camera not in cameras_by_vpp[board["aerodrome_id"]]:
                cameras_by_vpp[board["aerodrome_id"]].append(core_camera)
    vpps = [
        VPP(
            id=item["id"],
            name=item["id"],
            lat=item["lat"],
            lon=item["lon"],
            alt_m=0.0,
            uavs=by_vpp[item["id"]],
            cameras=cameras_by_vpp[item["id"]],
        )
        for item in aerodromes
        if by_vpp[item["id"]]
    ]
    params = _params(scenario, criterion_name, dem_path, symbols)
    mission = MissionInput(
        areas=[area],
        obstacles=obstacles,
        vpps=vpps,
        uavs=uavs,
        params=params,
        dem=dem,
    )
    return mission, notes


def _params(scenario: dict[str, Any], criterion_name: str, dem_path: Path, symbols: dict[str, Any]) -> Any:
    Params = symbols["Params"]
    Wind = symbols["Wind"]
    Criterion = symbols["Criterion"]
    gsd = scenario.get("gsd_cm_per_px")
    if isinstance(gsd, bool) or not isinstance(gsd, (int, float)) or gsd <= 0:
        raise ValueError("missing fields: gsd_cm_per_px")
    survey = scenario.get("survey")
    if not isinstance(survey, dict):
        raise ValueError("missing fields: survey")
    side = _fraction(survey.get("side_overlap"), "survey.side_overlap")
    forward = _fraction(survey.get("forward_overlap"), "survey.forward_overlap")
    angle = _angle(survey.get("strip_direction_deg"), "survey.strip_direction_deg")
    wind = scenario.get("wind")
    if not isinstance(wind, dict):
        raise ValueError("missing fields: wind")
    speed = wind.get("speed_ms")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or speed < 0:
        raise ValueError("missing fields: wind.speed_ms")
    direction = _angle(wind.get("direction_deg"), "wind.direction_deg")
    return Params(
        gsd_cm_per_px=float(gsd),
        wind=Wind(speed_mps=float(speed), direction_deg=direction),
        optimization_criterion=Criterion(criterion_name),
        overlap_x=side,
        overlap_long=forward,
        angles_deg=[angle],
        attempts_max=1,
        dem_file=str(dem_path),
    )


def _run_pipeline(mission: Any) -> Any | None:
    symbols = _core_symbols()
    counters = symbols["Counters"]()
    candidates = []
    for theta in mission.params.angles_deg:
        counters.reset_attempts()
        candidate = None
        for _ in range(mission.params.attempts_max):
            candidate = symbols["run_one_angle"](
                mission=mission,
                angle_deg=theta,
                counters=counters,
            )
            if candidate is not None:
                candidates.append(candidate)
                break
    if not candidates:
        return None
    return symbols["select_best"](candidates, mission.params.optimization_criterion)


def _plan(
    candidate: Any,
    mission: Any,
    dem_file: str,
    constraints: list[ConstraintPolygon],
) -> dict[str, Any]:
    routes = []
    for route in candidate.routes:
        routes.append(
            {
                "uav_id": route.uav_id,
                "vpp_id": route.vpp_id,
                "flight_index": route.flight_index,
                "waypoints": [
                    {"lat": point.lat, "lon": point.lon, "alt_m": point.alt_m}
                    for point in route.waypoints
                ],
            }
        )
    return {
        "solver": "pipeline",
        "criterion": mission.params.optimization_criterion.value,
        "crs": "EPSG:4326",
        "dem_file": dem_file,
        "constraint_polygons": [polygon.as_dict() for polygon in constraints],
        "obstacles": [obstacle.model_dump() for obstacle in mission.obstacles],
        "routes": routes,
        "mission": {
            "mission_time_s": candidate.C_max_s,
            "total_flight_time_s": candidate.flight_hours_s,
            "uav_used": candidate.n_uavs_used,
        },
        "validation": {"valid": True},
    }


def _core_symbols() -> dict[str, Any]:
    cached = getattr(_core_symbols, "cached", None)
    if cached is not None:
        return cached
    root = str(_CORE_SRC)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from planner.io.catalog import get_default_catalog
        from planner.io.dem.loader import load_dem
        from planner.models import (
            Area,
            Criterion,
            MissionInput,
            Obstacle,
            Params,
            SurveyType,
            UAVConfig,
            VPP,
            Wind,
        )
        from planner.solver.counters import Counters
        from planner.solver.pipeline import run_one_angle, select_best
    except ImportError as exc:
        raise ValueError(f"geo core import failed: {exc}") from exc
    cached = {
        "get_default_catalog": get_default_catalog,
        "load_dem": load_dem,
        "Area": Area,
        "Criterion": Criterion,
        "MissionInput": MissionInput,
        "Obstacle": Obstacle,
        "Params": Params,
        "SurveyType": SurveyType,
        "UAVConfig": UAVConfig,
        "VPP": VPP,
        "Wind": Wind,
        "Counters": Counters,
        "run_one_angle": run_one_angle,
        "select_best": select_best,
    }
    _core_symbols.cached = cached  # type: ignore[attr-defined]
    return cached


def _translate_model(model_id: str, catalog: Any) -> str:
    mapped = _MODEL_IDS.get(model_id)
    if mapped is None:
        raise ValueError(f"unknown uav model: {model_id}")
    try:
        catalog.get_aircraft(mapped)
    except KeyError as exc:
        raise ValueError(f"geo core has no aircraft {mapped}") from exc
    return mapped


def _translate_camera(camera_id: str, catalog: Any) -> str:
    mapped = _CAMERA_IDS.get(camera_id)
    if mapped is None:
        raise ValueError(f"unknown camera: {camera_id}")
    try:
        catalog.get_camera(mapped)
    except KeyError as exc:
        raise ValueError(f"geo core has no camera {mapped}") from exc
    return mapped


def _aerodromes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw or len(raw) > 4:
        raise ValueError("missing fields: aerodromes")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: aerodromes[{index}]")
        aerodrome_id = _text(item.get("id"), f"aerodromes[{index}].id")
        if aerodrome_id in seen:
            raise ValueError(f"duplicate aerodrome id: {aerodrome_id}")
        seen.add(aerodrome_id)
        found.append(
            {
                "id": aerodrome_id,
                "lat": _coord(item.get("lat"), f"aerodromes[{index}].lat", -90, 90),
                "lon": _coord(item.get("lon"), f"aerodromes[{index}].lon", -180, 180),
            }
        )
    return found


def _boards(raw: Any, aerodromes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("missing fields: boards")
    known = {item["id"] for item in aerodromes}
    found: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: boards[{index}]")
        board_id = _text(item.get("id"), f"boards[{index}].id")
        aerodrome_id = _text(item.get("aerodrome_id"), f"boards[{index}].aerodrome_id")
        if aerodrome_id not in known:
            raise ValueError(f"unknown aerodrome: {aerodrome_id}")
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"missing fields: boards[{index}].count")
        found.append(
            {
                "id": board_id,
                "model_id": _text(item.get("model_id"), f"boards[{index}].model_id"),
                "camera_id": _text(item.get("camera_id"), f"boards[{index}].camera_id"),
                "aerodrome_id": aerodrome_id,
                "count": count,
            }
        )
    return found


def _edges(
    catalog: dict[str, Any],
    models: dict[str, dict[str, Any]],
    cameras: dict[str, dict[str, Any]],
) -> set[tuple[str, str]]:
    raw = catalog.get("compatibility")
    if not isinstance(raw, list):
        raise ValueError("missing fields: compatibility")
    found: set[tuple[str, str]] = set()
    for index, edge in enumerate(raw):
        if not isinstance(edge, dict):
            raise ValueError(f"missing fields: compatibility[{index}]")
        model_id = _text(edge.get("uav_model_id"), f"compatibility[{index}].uav_model_id")
        camera_id = _text(edge.get("camera_id"), f"compatibility[{index}].camera_id")
        if model_id not in models or camera_id not in cameras:
            raise ValueError(f"unknown catalog edge: {model_id} {camera_id}")
        found.add((model_id, camera_id))
    return found


def _index(raw: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError(f"missing fields: {label}")
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"missing fields: {label}[{index}]")
        row_id = _text(item.get("id"), f"{label}[{index}].id")
        indexed[row_id] = item
    return indexed


def _spectra(camera: dict[str, Any]) -> tuple[str, ...]:
    raw = camera.get("spectra")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing fields: {label}")
    return value


def _optional_text(value: Any) -> str:
    if value is None:
        raise ValueError("missing fields: constraints_kml")
    if not isinstance(value, str):
        raise ValueError("missing fields: constraints_kml")
    return value


def _coord(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    number = float(value)
    if number < low or number > high:
        raise ValueError(f"missing fields: {label}")
    return number


def _fraction(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    number = float(value)
    if number < 0 or number >= 1:
        raise ValueError(f"missing fields: {label}")
    return number


def _angle(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing fields: {label}")
    number = float(value)
    if number < 0 or number > 360:
        raise ValueError(f"missing fields: {label}")
    if number == 360:
        return 0.0
    return number


def _log(job_id: str, lines: tuple[str, ...] | list[str]) -> None:
    body = "\n".join(lines) if lines else "geo core: no limitation lines"
    record(job_id, f"job_id={job_id} geo-core\n{body}")
