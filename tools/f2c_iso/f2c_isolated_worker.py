#!/usr/bin/env python3
"""Isolated Fields2Cover worker — runs ONLY under embed venv.

Reads a /v0/solve-shaped JSON request on stdin (or --file), writes a
ComputeResponse-shaped JSON on stdout. Uses local engine copy that never
adds mvp_optimizator/src to sys.path (avoids sitecustomize / absl ABI clash).

Expected invocation:
  env -u PYTHONPATH -u PYTHONHOME PYTHONNOUSERSITE=1 \\
    $F2C_EMBED_PYTHON f2c_isolated_worker.py --file req.json

Deploy default embed is ``$PLANES_GRISHA_ROOT/.venv-f2c-embed``
(``PLANES_GRISHA_ROOT`` defaults to ``/opt/planes-grisha-f2c``).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Worker dir must be first so fields2cover_engine_iso / constraints resolve here.
_HERE = Path(__file__).resolve().parent
_ISO_SRC = _HERE / "iso_src"
if str(_ISO_SRC) not in sys.path:
    sys.path.insert(0, str(_ISO_SRC))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Import ortools BEFORE fields2cover (ABI preference for embed stack).
import ortools  # noqa: F401

from fields2cover_engine_iso import (  # noqa: E402
    BoardCamera,
    BudgetExhausted,
    CoverageInfeasible,
    EngineContext,
    bind_context,
    marked_number,
    optics,
    plan,
    reset_context,
)
from wave_b import read_recharge_time_s, read_wave_b_flags  # noqa: E402

try:
    from constraints import parse_constraint_polygons, parse_survey_polygon
except ImportError:  # when iso_src not on path but sibling
    from iso_src.constraints import parse_constraint_polygons, parse_survey_polygon  # type: ignore


def _grisha_root() -> Path:
    return Path(os.environ.get("PLANES_GRISHA_ROOT", "/opt/planes-grisha-f2c"))


def _repo_root() -> Path:
    # tools/f2c_iso/f2c_isolated_worker.py → repository root
    return _HERE.parents[1]


def _catalog_candidates() -> tuple[Path, ...]:
    env = os.environ.get("PLANES_FLEET_CATALOG")
    prefixed = (Path(env),) if env else ()
    return prefixed + (
        _repo_root() / "catalog" / "fleet_catalog.json",
        _grisha_root() / "catalog" / "fleet_catalog.json",
        Path("/opt/planes/src/planes/runtime/catalog/fleet_catalog.json"),
        _ISO_SRC / "fleet_catalog.json",
    )


def _resolve_catalog_path() -> Path:
    for cand in _catalog_candidates():
        if cand.is_file():
            return cand
    return _catalog_candidates()[-1]


@dataclass
class _Vpp:
    id: str
    lat: float
    lon: float


@dataclass
class _Area:
    id: str
    polygon: dict[str, Any]


@dataclass
class _Obstacle:
    polygon: dict[str, Any]


@dataclass
class _Params:
    angles_deg: list[float]


@dataclass
class _MonoDem:
    """Flat ground h=0 — legacy default when no dem_file is provided."""

    def h(self, lat: float, lon: float) -> float:
        del lat, lon
        return 0.0

    def is_empty(self) -> bool:
        return True


class _GeoTiffDem:
    """GeoTIFF DEM matching mvp BaseDEM.h(lat, lon) / is_empty().

    Inline (no mvp_optimizator import) so the isolated worker stays free of
    sitecustomize / absl. Uses rasterio when available in the embed venv.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._arr = None
        self._transform = None
        self._nodata = None
        self._error: str | None = None
        self._loaded = False
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded or self._error is not None:
            return
        if not self.path.is_file():
            self._error = f"GeoTIFF not found: {self.path}"
            return
        try:
            import numpy as np
            import rasterio
        except ImportError as exc:
            self._error = f"rasterio/numpy unavailable: {exc}"
            return
        try:
            with rasterio.open(self.path) as src:
                self._arr = src.read(1).astype("float32")
                self._transform = src.transform
                self._nodata = src.nodata
            self._loaded = True
            self._np = np
        except Exception as exc:  # noqa: BLE001 — surface as empty DEM
            self._error = f"Failed to read GeoTIFF: {exc}"

    def is_empty(self) -> bool:
        return self._arr is None

    @property
    def error(self) -> str | None:
        return self._error

    def h(self, lat: float, lon: float) -> float:
        if self._arr is None or self._transform is None:
            return 0.0
        np = self._np
        col_f, row_f = ~self._transform * (lon, lat)
        rows, cols = self._arr.shape
        if not (0 <= col_f < cols and 0 <= row_f < rows):
            col_f = min(max(col_f, 0.0), cols - 1.001)
            row_f = min(max(row_f, 0.0), rows - 1.001)
        col = int(math.floor(col_f))
        row = int(math.floor(row_f))
        fx = col_f - col
        fy = row_f - row
        c1 = min(col + 1, cols - 1)
        r1 = min(row + 1, rows - 1)

        def pix(r: int, c: int) -> float:
            val = float(self._arr[r, c])
            if self._nodata is not None and abs(val - float(self._nodata)) < 1e-3:
                return 0.0
            if np.isnan(val):
                return 0.0
            return val

        return (
            pix(row, col) * (1 - fx) * (1 - fy)
            + pix(row, c1) * fx * (1 - fy)
            + pix(r1, col) * (1 - fx) * fy
            + pix(r1, c1) * fx * fy
        )

    def h_max(self) -> float:
        if self._arr is None:
            return 0.0
        return float(self._np.nanmax(self._arr))

    def h_min(self) -> float:
        if self._arr is None:
            return 0.0
        return float(self._np.nanmin(self._arr))


def _scenario_dem_path(scenario: dict[str, Any]) -> str | None:
    """Resolve DEM path from scenario (API / Mission.dem / dem_file)."""
    for key in ("dem_file", "dem_geotiff", "dem_path", "dem"):
        raw = scenario.get(key)
        if isinstance(raw, str) and raw.strip() and raw.strip().lower() not in {"mono", "flat", "none"}:
            return raw.strip()
        if isinstance(raw, dict):
            for sub in ("path", "file", "geotiff", "url_local"):
                v = raw.get(sub)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _load_mission_dem(scenario: dict[str, Any]) -> tuple[Any, str, list[str]]:
    """Return (dem, dem_label, limitations).

    When dem_file points at a readable GeoTIFF → _GeoTiffDem.
    Otherwise keep _MonoDem (h=0) so live behaviour is unchanged.
    """
    notes: list[str] = []
    path = _scenario_dem_path(scenario)
    if path is None:
        notes.append("temporary flat terrain; OpenTopography was not called")
        notes.append("dem_file: mono")
        return _MonoDem(), "mono", notes

    dem = _GeoTiffDem(path)
    if dem.is_empty():
        notes.append(f"dem_file present but unreadable → mono fallback ({dem.error})")
        notes.append("dem_file: mono")
        return _MonoDem(), "mono", notes

    notes.append(f"dem_file: {path}")
    notes.append("terrain ASL = DEM.h(lat,lon) + h_agl_m (iso path)")
    notes.append("iso duration remains 2D path/speed — climb/descent time NOT applied")
    if scenario.get("terrain_corridor"):
        notes.append("terrain_corridor requested but NOT applied on iso path (mvp_optimizator only)")
    return dem, str(path), notes


def _clearance_violations(
    routes: list[dict[str, Any]],
    dem: Any,
    safety_margin_m: float,
    h_agl_by_uav: dict[str, float],
) -> list[str]:
    """Report waypoints where ASL - DEM < safety_margin (diag / refuse signal)."""
    if safety_margin_m <= 0 or dem is None:
        return []
    try:
        if dem.is_empty():
            return []
    except AttributeError:
        pass
    errs: list[str] = []
    for r in routes:
        uav = str(r.get("uav_id") or "")
        # Prefer optics h_agl; fall back to margin-only check vs DEM
        for i, wp in enumerate(r.get("waypoints") or []):
            lat = float(wp["lat"])
            lon = float(wp["lon"])
            alt = float(wp["alt_m"])
            dem_h = float(dem.h(lat, lon))
            h_agl = alt - dem_h
            if h_agl < safety_margin_m - 1e-3:
                errs.append(
                    f"UAV {uav} wp{i} ({lat:.5f},{lon:.5f}): "
                    f"h_agl={h_agl:.1f}m < safety={safety_margin_m:.1f}m"
                )
                if len(errs) >= 8:
                    return errs
    return errs


@dataclass
class _Mission:
    vpps: list[_Vpp]
    areas: list[_Area]
    obstacles: list[_Obstacle]
    params: _Params
    dem: Any = field(default_factory=_MonoDem)


def _val(record: dict[str, Any], key: str, default: float | None = None) -> float:
    raw = record.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        if default is not None:
            return float(default)
        raise ValueError(f"missing fields: {key}")
    return float(raw)


def _load_catalog() -> dict[str, Any]:
    path = _resolve_catalog_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("fleet catalog unreadable: not an object")
    return raw


def _index(items: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


def _ring_to_polygon(ring: list[list[float]] | tuple) -> dict[str, Any]:
    coords = [[float(lon), float(lat)] for lon, lat in ring]
    if coords and coords[0] != coords[-1]:
        coords.append(list(coords[0]))
    return {"type": "Polygon", "coordinates": [coords]}


def _areas_from_kml(survey_kml: str) -> list[_Area]:
    polys = parse_survey_polygon(survey_kml)
    areas: list[_Area] = []
    for i, poly in enumerate(polys, start=1):
        areas.append(
            _Area(
                id=poly.name or f"survey-{i}",
                polygon=_ring_to_polygon(poly.ring),
            )
        )
    return areas


def _areas_from_geojson(raw_areas: list[dict[str, Any]]) -> list[_Area]:
    out: list[_Area] = []
    for i, area in enumerate(raw_areas, start=1):
        poly = area.get("polygon") or area
        if "coordinates" not in poly:
            raise ValueError(f"area {i} missing polygon.coordinates")
        out.append(
            _Area(
                id=str(area.get("id") or f"survey-{i}"),
                polygon={
                    "type": "Polygon",
                    "coordinates": poly["coordinates"],
                },
            )
        )
    return out


def _obstacles_from_kml(text: str | None) -> list[_Obstacle]:
    polys = parse_constraint_polygons(text)
    return [_Obstacle(polygon=_ring_to_polygon(p.ring)) for p in polys]


def _obstacles_from_geojson(raw: list[dict[str, Any]] | None) -> list[_Obstacle]:
    if not raw:
        return []
    out: list[_Obstacle] = []
    for item in raw:
        poly = item.get("polygon") or item
        out.append(_Obstacle(polygon={"type": "Polygon", "coordinates": poly["coordinates"]}))
    return out


def _compat_edges(catalog: dict[str, Any]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for edge in catalog.get("compatibility") or []:
        if not isinstance(edge, dict):
            continue
        mid = edge.get("uav_model_id")
        cid = edge.get("camera_id")
        if mid is None or cid is None:
            continue
        edges.add((str(mid), str(cid)))
    return edges


def _board_speed_m_s(model: dict[str, Any]) -> float:
    """Prefer CAT-001C survey_speed_m_s when present; else passport airspeed."""
    if model.get("survey_speed_m_s") is not None:
        return _val(model, "survey_speed_m_s")
    return _val(model, "airspeed_m_s")


def _board_endurance_s(model: dict[str, Any]) -> float:
    """flight_time_s with optional reserve_fraction (battery Wh not used for packing)."""
    endurance = _val(model, "flight_time_s")
    if model.get("reserve_fraction") is not None:
        reserve = _val(model, "reserve_fraction")
        if not (0.0 <= reserve < 1.0):
            raise ValueError(f"reserve_fraction out of range for model {model.get('id')}")
        endurance = endurance * (1.0 - reserve)
    return endurance


def _expand_boards(
    scenario: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[list[_Vpp], tuple[BoardCamera, ...]]:
    models = _index(catalog["uav_models"])
    cameras = _index(catalog["cameras"])
    edges = _compat_edges(catalog)
    aeros_raw = scenario.get("aerodromes") or []
    if not aeros_raw:
        raise ValueError("missing fields: aerodromes")
    vpps = [
        _Vpp(id=str(a["id"]), lat=float(a["lat"]), lon=float(a["lon"]))
        for a in aeros_raw
    ]
    aero_by_id = {v.id: v for v in vpps}
    survey = scenario.get("survey") or {}
    side_overlap = float(survey.get("side_overlap", 0.5))
    gsd = float(scenario.get("gsd_cm_per_px", 2.0))
    flags = read_wave_b_flags(scenario)
    boards_out: list[BoardCamera] = []
    for card in scenario.get("boards") or []:
        model_id = str(card["model_id"])
        camera_id = str(card["camera_id"])
        if model_id not in models:
            raise ValueError(f"uav model {model_id} not in catalog")
        if camera_id not in cameras:
            raise ValueError(f"camera {camera_id} not in catalog")
        if edges and (model_id, camera_id) not in edges:
            raise ValueError(
                f"camera {camera_id} is not compatible with model {model_id}"
            )
        model = models[model_id]
        camera = cameras[camera_id]
        aero_id = str(card["aerodrome_id"])
        if aero_id not in aero_by_id:
            raise ValueError(f"unknown aerodrome: {aero_id}")
        aero = aero_by_id[aero_id]
        count = int(card.get("count") or 1)
        speed = _board_speed_m_s(model)
        endurance = _board_endurance_s(model)
        if speed <= 0 or endurance <= 0:
            raise ValueError(
                f"model {model_id} has no positive endurance or survey/airspeed"
            )
        recharge_s = read_recharge_time_s(model, card, flags)
        spacing_m, h_agl_m = optics(camera, gsd, side_overlap)
        base_id = str(card["id"])
        for n in range(count):
            uid = base_id if count == 1 else f"{base_id}#{n + 1}"
            boards_out.append(
                BoardCamera(
                    uav_id=uid,
                    vpp_id=aero.id,
                    lat=aero.lat,
                    lon=aero.lon,
                    endurance_s=endurance,
                    speed_m_s=speed,
                    spacing_m=spacing_m,
                    h_agl_m=h_agl_m,
                    recharge_time_s=recharge_s,
                )
            )
    if not boards_out:
        raise ValueError("no boards")
    return vpps, tuple(boards_out)


def _route_dict(route: Any) -> dict[str, Any]:
    takeoff_id = str(getattr(route, "takeoff_vpp_id", None) or route.vpp_id)
    landing_id = str(getattr(route, "landing_vpp_id", None) or route.vpp_id)
    return {
        "uav_id": route.uav_id,
        "vpp_id": takeoff_id,
        "takeoff_vpp_id": takeoff_id,
        "landing_vpp_id": landing_id,
        "flight_index": int(route.flight_index),
        "start_time_s": float(getattr(route, "start_time_s", 0.0) or 0.0),
        "recharge_before_s": float(getattr(route, "recharge_before_s", 0.0) or 0.0),
        "waypoints": [
            {"lat": float(wp.lat), "lon": float(wp.lon), "alt_m": float(wp.alt_m)}
            for wp in route.waypoints
        ],
        "T_total_s": float(route.T_total_s),
    }


def _swath_stats(routes: list[dict[str, Any]]) -> dict[str, Any]:
    """Rough path length + swath-ish count (segments between aerodrome hops)."""
    path_m = 0.0
    n_wp = 0
    for route in routes:
        wps = route["waypoints"]
        n_wp += len(wps)
        for i in range(len(wps) - 1):
            path_m += _hav_m(wps[i], wps[i + 1])
    return {"path_m": path_m, "n_waypoints": n_wp, "n_routes": len(routes)}


def _hav_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    R = 6371000.0
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def solve_request(req: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    # Prove isolation environment
    iso = {
        "python": sys.executable,
        "pythonpath": sys.path[:8],
        "ortools_ok": True,
        "fields2cover_version": None,
        "sitecustomize_module": None,
        "sitecustomize_file": None,
        "grisha_sitecustomize": False,
        "mvp_on_path": any("mvp_optimizator" in p for p in sys.path),
    }
    import fields2cover as f2c  # noqa: F401
    import importlib.metadata as metadata

    iso["fields2cover_version"] = metadata.version("fields2cover")
    iso["fields2cover_file"] = getattr(f2c, "__file__", None)
    # Ubuntu ships /usr/lib/python3.*/sitecustomize.py (apport) — that is OK.
    # Grisha mvp sitecustomize.py breaks absl ABI; reject only that one.
    if "sitecustomize" in sys.modules:
        sc = sys.modules["sitecustomize"]
        sc_file = getattr(sc, "__file__", None) or ""
        iso["sitecustomize_module"] = True
        iso["sitecustomize_file"] = sc_file
        iso["grisha_sitecustomize"] = "mvp_optimizator" in sc_file.replace("\\", "/")
    else:
        iso["sitecustomize_module"] = False

    if iso["mvp_on_path"] or iso["grisha_sitecustomize"]:
        raise RuntimeError(
            f"isolation violated: mvp_on_path={iso['mvp_on_path']} "
            f"grisha_sitecustomize={iso['grisha_sitecustomize']} "
            f"sitecustomize_file={iso['sitecustomize_file']} path={sys.path}"
        )

    scenario = req.get("scenario") or {}
    opt = req.get("optimization") or {}
    limit = float(opt.get("time_limit_seconds") or 120)
    deadline = time.monotonic() + limit
    catalog = _load_catalog()
    vpps, boards = _expand_boards(scenario, catalog)

    if scenario.get("survey_kml"):
        areas = _areas_from_kml(scenario["survey_kml"])
    elif scenario.get("areas"):
        areas = _areas_from_geojson(scenario["areas"])
    else:
        raise ValueError("scenario needs survey_kml or areas")

    if scenario.get("constraints_kml") is not None or scenario.get("constraints_kml"):
        obstacles = _obstacles_from_kml(scenario.get("constraints_kml"))
    else:
        obstacles = _obstacles_from_geojson(scenario.get("obstacles") or scenario.get("constraint_polygons"))

    survey = scenario.get("survey") or {}
    # Live Grisha/F2C contour: strip_direction_deg is ignored; auto via generateBestSwaths.
    _ = survey.get("strip_direction_deg")
    dem_obj, dem_label, dem_notes = _load_mission_dem(scenario)
    safety_margin_m = float(scenario.get("safety_margin_m") or 0.0)
    strict_terrain_check = bool(scenario.get("strict_terrain_check") or False)
    mission = _Mission(
        vpps=vpps,
        areas=areas,
        obstacles=obstacles,
        params=_Params(angles_deg=[]),  # empty → auto-angle in iso engine
        dem=dem_obj,
    )

    flags = read_wave_b_flags(scenario)
    token = bind_context(
        EngineContext(
            deadline=deadline,
            boards=boards,
            pads=tuple(vpps),
            allow_recharge=flags.allow_recharge,
            allow_foreign_landing=flags.allow_foreign_landing,
            allow_foreign_takeoff=flags.allow_foreign_takeoff,
            min_separation_m=flags.min_separation_m,
            time_window_s=flags.time_window_s,
        )
    )
    try:
        candidate = plan(mission)
    except CoverageInfeasible as exc:
        wall = time.perf_counter() - t0
        return {
            "contract_version": req.get("contract_version", "v0"),
            "job_id": req.get("job_id", "f2c-iso"),
            "outcome": "infeasible",
            "isolation": iso,
            "solver_report": {
                "method": "grisha_mvp_fields2cover_isolated",
                "runtime_seconds": wall,
                "limitations": [
                    str(exc.reason),
                    f"uncovered_swaths={exc.uncovered}",
                    *list(exc.limitations),
                    f"allow_recharge={flags.allow_recharge}",
                ],
            },
            "mission_plan": None,
            "error": exc.reason,
            "uncovered_swath_count": exc.uncovered,
        }
    except BudgetExhausted:
        wall = time.perf_counter() - t0
        return {
            "contract_version": req.get("contract_version", "v0"),
            "job_id": req.get("job_id", "f2c-iso"),
            "outcome": "timed_out",
            "isolation": iso,
            "solver_report": {
                "method": "grisha_mvp_fields2cover_isolated",
                "runtime_seconds": wall,
                "limitations": ["budget exhausted before route"],
            },
            "mission_plan": None,
            "error": "BudgetExhausted",
        }
    finally:
        reset_context(token)

    wall = time.perf_counter() - t0
    if candidate is None:
        return {
            "contract_version": req.get("contract_version", "v0"),
            "job_id": req.get("job_id", "f2c-iso"),
            "outcome": "infeasible",
            "isolation": iso,
            "solver_report": {
                "method": "grisha_mvp_fields2cover_isolated",
                "runtime_seconds": wall,
                "limitations": ["no swaths"],
            },
            "mission_plan": None,
        }

    routes = [_route_dict(r) for r in candidate.routes]
    stats = _swath_stats(routes)
    clearance_errs = _clearance_violations(
        routes,
        dem_obj,
        safety_margin_m,
        {str(b.uav_id): float(b.h_agl_m) for b in boards},
    )
    if clearance_errs:
        dem_notes = list(dem_notes) + [
            f"safety_margin_m={safety_margin_m}: {len(clearance_errs)} clearance violation(s) detected"
        ] + clearance_errs[:5]
        if strict_terrain_check:
            wall = time.perf_counter() - t0
            return {
                "contract_version": req.get("contract_version", "v0"),
                "job_id": req.get("job_id", "f2c-iso"),
                "outcome": "infeasible",
                "isolation": iso,
                "solver_report": {
                    "method": "grisha_mvp_fields2cover_isolated",
                    "runtime_seconds": wall,
                    "limitations": dem_notes + ["strict_terrain_check refused plan"],
                },
                "mission_plan": None,
                "error": "terrain_clearance_violation",
            }
    return {
        "contract_version": req.get("contract_version", "v0"),
        "job_id": req.get("job_id", "f2c-iso"),
        "outcome": "feasible",
        "isolation": iso,
        "solver_report": {
            "method": "grisha_mvp_fields2cover_isolated",
            "objective": (opt.get("objective") or "min_time"),
            "runtime_seconds": wall,
            "seed": req.get("seed"),
            "limitations": [
                "isolated embed venv fields2cover 2.1.0 + ortools 9.9",
                "decomposition=fields2cover; angle via SG_BruteForce.generateBestSwaths (strip_direction_deg ignored)",
                "Grisha mvp sitecustomize NOT on worker path; F2C in clean subprocess",
                *dem_notes,
                *list(getattr(candidate, "extra_limitations", ()) or ()),
                "heuristic result is not globally optimal",
                f"fleet_catalog={_resolve_catalog_path()}",
                "board speed=survey_speed_m_s when present else airspeed_m_s; endurance=flight_time_s*(1-reserve_fraction); battery Wh not used for packing",
                (
                    f"wave_b allow_recharge={flags.allow_recharge} "
                    f"allow_foreign_landing={flags.allow_foreign_landing} "
                    f"allow_foreign_takeoff={flags.allow_foreign_takeoff} "
                    f"min_separation_m={flags.min_separation_m} "
                    f"time_window_s={flags.time_window_s}"
                ),
                "wave_b: mission_time_s includes recharge gaps and separation delays; total_flight_time_s is airborne only",
            ],
        },
        "mission_plan": {
            "solver": "grisha_mvp_fields2cover",
            "engine": "f2c_isolated_generateBestSwaths",
            "criterion": scenario.get("criterion") or "min_time",
            "crs": scenario.get("crs") or "EPSG:4326",
            "dem_file": dem_label,
            "areas": [
                {
                    "id": a.id,
                    "name": a.id,
                    "survey_type": "visible",
                    "polygon": a.polygon,
                }
                for a in areas
            ],
            "constraint_polygons": [],
            "obstacles": [{"polygon": o.polygon} for o in obstacles],
            "routes": [
                {
                    "uav_id": r["uav_id"],
                    "vpp_id": r["vpp_id"],
                    "takeoff_vpp_id": r.get("takeoff_vpp_id", r["vpp_id"]),
                    "landing_vpp_id": r.get("landing_vpp_id", r["vpp_id"]),
                    "flight_index": r["flight_index"],
                    "start_time_s": r.get("start_time_s", 0.0),
                    "recharge_before_s": r.get("recharge_before_s", 0.0),
                    "waypoints": r["waypoints"],
                }
                for r in routes
            ],
            "mission": {
                "mission_time_s": float(candidate.C_max_s),
                "total_flight_time_s": float(candidate.flight_hours_s),
                "uav_used": int(candidate.n_uavs_used),
                "recharge_gap_s": float(getattr(candidate, "recharge_gap_s", 0.0) or 0.0),
                "separation_delay_s": float(getattr(candidate, "separation_delay_s", 0.0) or 0.0),
            },
            "wave_b": {
                "allow_recharge": flags.allow_recharge,
                "allow_foreign_landing": flags.allow_foreign_landing,
                "allow_foreign_takeoff": flags.allow_foreign_takeoff,
                "min_separation_m": flags.min_separation_m,
                "time_window_s": flags.time_window_s,
                "recharge_gap_s": float(getattr(candidate, "recharge_gap_s", 0.0) or 0.0),
                "separation_delay_s": float(getattr(candidate, "separation_delay_s", 0.0) or 0.0),
                "uncovered_swath_count": int(getattr(candidate, "uncovered_swath_count", 0) or 0),
            },
            "validation": {
                "valid": len(clearance_errs) == 0,
                "terrain_clearance_errors": clearance_errs,
                "safety_margin_m": safety_margin_m,
                "terrain_corridor_applied": False,
                "climb_model_applied": False,
            },
            "stats": stats,
            "theta_deg": float(candidate.theta_deg),
            "decomposition_method": candidate.decomposition_method,
            "board_optics": [
                {
                    "uav_id": b.uav_id,
                    "spacing_m": float(b.spacing_m),
                    "h_agl_m": float(b.h_agl_m),
                    "speed_m_s": float(b.speed_m_s),
                    "endurance_s": float(b.endurance_s),
                    "recharge_time_s": float(b.recharge_time_s),
                }
                for b in boards
            ],
            "catalog_path": str(_resolve_catalog_path()),
        },
        "artifacts": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Isolated F2C worker")
    ap.add_argument("--file", "-f", help="Request JSON path (else stdin)")
    ap.add_argument("--self-check", action="store_true", help="Tiny synthetic smoke")
    args = ap.parse_args()

    try:
        if args.self_check:
            # Tiny rectangle near Moscow
            req = {
                "contract_version": "v0",
                "job_id": "f2c-iso-smoke",
                "seed": 7,
                "optimization": {"objective": "min_time", "time_limit_seconds": 30},
                "scenario": {
                    "crs": "EPSG:4326",
                    "criterion": "min_time",
                    "gsd_cm_per_px": 2.0,
                    "required_spectrum": "RGB",
                    "aerodromes": [{"id": "аэродром 1", "lat": 55.748, "lon": 37.604}],
                    "boards": [
                        {
                            "id": "БВС 1",
                            "model_id": "geoscan-gemini",
                            "camera_id": "geoscan-pf1b",
                            "aerodrome_id": "аэродром 1",
                            "count": 1,
                        }
                    ],
                    "survey": {
                        "forward_overlap": 0.6,
                        "side_overlap": 0.5,
                        "strip_direction_deg": 0,
                    },
                    "areas": [
                        {
                            "id": "survey-1",
                            "polygon": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [37.6, 55.75],
                                        [37.608, 55.75],
                                        [37.608, 55.754],
                                        [37.6, 55.754],
                                        [37.6, 55.75],
                                    ]
                                ],
                            },
                        }
                    ],
                },
            }
        elif args.file:
            req = json.loads(Path(args.file).read_text(encoding="utf-8"))
        else:
            req = json.load(sys.stdin)

        resp = solve_request(req)
        json.dump(resp, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0 if resp.get("outcome") == "feasible" else 2
    except Exception as exc:
        err = {
            "outcome": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "python": sys.executable,
            "sys_path": sys.path[:12],
            "sitecustomize_loaded": "sitecustomize" in sys.modules,
        }
        json.dump(err, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
