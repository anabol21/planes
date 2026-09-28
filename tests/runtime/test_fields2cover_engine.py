"""Fields2Cover listener engine.

The rectangle is the survey-one fallback ring. Native Fields2Cover and the
old ``planner.solver`` extension cannot share one process, so the route
cases run in a fresh interpreter. A spectrum miss stays in this process and
must not import Fields2Cover.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from planes.runtime.solver import Infeasible, Problem, Solution, solve


_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SURVEY = (_FIXTURES / "stitch_survey.kml").read_text(encoding="utf-8")
_REPO = Path(__file__).resolve().parents[2]


class _Dem:
    def __init__(self, height: float) -> None:
        self.height = height

    def h(self, lat: float, lon: float) -> float:
        del lat, lon
        return self.height


class Fields2CoverEngineTest(unittest.TestCase):
    def test_rectangle_routes_without_ortools(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        env["PLANES_F2C_CASES"] = "1"
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=_REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + "\n" + completed.stderr,
        )
        self.assertIn("fields2cover cases ok", completed.stdout)
        self.assertIn("rectangle_s=", completed.stdout)

    def test_spectrum_miss_does_not_call_fields2cover(self) -> None:
        import planes.runtime.fields2cover_engine as engine

        calls: list[str] = []

        def boom():
            calls.append("fields2cover")
            raise AssertionError("Fields2Cover called on a spectrum miss")

        original_import = engine._fields2cover
        engine._fields2cover = boom
        scenario = {
            "crs": "EPSG:4326",
            "criterion": "min_time",
            "gsd_cm_per_px": 2,
            "required_spectrum": "RGB",
            "survey_kml": _SURVEY,
            "constraints_kml": "",
            "aerodromes": [{"id": "аэродром 1", "lat": 55.748, "lon": 37.604}],
            "boards": [
                {
                    "id": "БВС 1",
                    "model_id": "geoscan-801",
                    "camera_id": "geoscan-801-thermal",
                    "aerodrome_id": "аэродром 1",
                    "count": 1,
                }
            ],
            "survey": {
                "forward_overlap": 0.6,
                "side_overlap": 0.5,
                "strip_direction_deg": 0,
            },
            "wind": {"speed_ms": 1, "direction_deg": 90},
        }
        try:
            result = solve(
                Problem(
                    job_id="job_f2c_spectrum",
                    scenario=scenario,
                    objective="min_time",
                    seed=7,
                    time_limit_seconds=30,
                ),
                time.monotonic() + 30,
            )
        finally:
            engine._fields2cover = original_import
        self.assertEqual(calls, [])
        self.assertIsInstance(result, Infeasible)
        assert isinstance(result, Infeasible)
        self.assertIn("no camera covers required spectrum", result.limitations)
        self.assertNotIsInstance(result, Solution)


def _run_cases() -> None:
    import math

    import fields2cover as f2c
    from shapely.geometry import Point, Polygon

    import planes.runtime.geo_mission as geo_mission
    from planes.runtime.fields2cover_engine import (
        FIELDS2COVER_VERSION,
        BoardCamera,
        BudgetExhausted,
        EngineContext,
        bind_context,
        optics,
        plan,
        reset_context,
    )

    import importlib.metadata as metadata

    version = metadata.version("fields2cover")
    assert version == FIELDS2COVER_VERSION == "2.1.0", version

    def forbid(*args, **kwargs):
        del args, kwargs
        raise AssertionError("OR-Tools route planner called")

    f2c.RP_RoutePlannerBase.genRoute = forbid

    ring = [
        (37.600, 55.750),
        (37.608, 55.750),
        (37.608, 55.754),
        (37.600, 55.754),
        (37.600, 55.750),
    ]
    hole = [
        (37.602, 55.751),
        (37.606, 55.751),
        (37.606, 55.753),
        (37.602, 55.753),
        (37.602, 55.751),
    ]
    spacing_m, h_agl_m = optics(_pf1b(), 2.0, 0.5)
    boards = (
        _board("БВС 1", spacing_m, h_agl_m),
        _board("БВС 2", spacing_m, h_agl_m),
    )
    mission = _mission(geo_mission, ring, boards)
    started = time.monotonic()
    candidate = _call(plan, bind_context, reset_context, EngineContext, mission, boards, 30)
    elapsed = time.monotonic() - started
    print(f"rectangle_s={elapsed:.3f}")
    assert elapsed < 8.0, elapsed
    assert candidate is not None
    assert candidate.decomposition_method == "fields2cover"
    assert {route.uav_id for route in candidate.routes} == {"БВС 1", "БВС 2"}
    assert candidate.C_max_s > 0.0
    assert "planner.solver.pipeline" not in sys.modules
    assert "planner.solver.routing" not in sys.modules
    for route in candidate.routes:
        assert route.flight_index >= 1
        assert route.waypoints[0].alt_m == 100.0
        assert route.waypoints[-1].alt_m == 100.0
        assert math.isclose(route.waypoints[1].alt_m, 100.0 + h_agl_m, abs_tol=1e-6)
    built = geo_mission._plan(candidate, mission, "dem.tif", [])
    assert built["solver"] == "fields2cover"
    assert "areas" in built and "obstacles" in built and "constraint_polygons" in built
    assert set(built["routes"][0]["waypoints"][0]) == {"lat", "lon", "alt_m"}

    narrow = _board("БВС narrow", 40.0, 80.0)
    wide = _board("БВС wide", 120.0, 160.0)
    mixed = _call(
        plan,
        bind_context,
        reset_context,
        EngineContext,
        _mission(geo_mission, ring, (narrow, wide)),
        (narrow, wide),
        30,
    )
    assert mixed is not None
    counts: dict[str, int] = {}
    for route in mixed.routes:
        counts[route.uav_id] = counts.get(route.uav_id, 0) + len(route.waypoints)
    assert counts["БВС narrow"] > counts["БВС wide"]

    holed = _call(
        plan,
        bind_context,
        reset_context,
        EngineContext,
        _mission(geo_mission, ring, boards[:1], hole=hole),
        boards[:1],
        30,
    )
    assert holed is not None and holed.routes
    hole_poly = Polygon(hole)
    for route in holed.routes:
        body = route.waypoints[1:-1]
        assert len(body) >= 2
        for index in range(0, len(body) - 1, 2):
            mid = Point(
                (body[index].lon + body[index + 1].lon) / 2.0,
                (body[index].lat + body[index + 1].lat) / 2.0,
            )
            assert not hole_poly.contains(mid)

    empty = _call(
        plan,
        bind_context,
        reset_context,
        EngineContext,
        _mission(geo_mission, ring, (_board("БВС 1", 50_000.0, 100.0),)),
        (_board("БВС 1", 50_000.0, 100.0),),
        30,
    )
    assert empty is None

    try:
        _call(
            plan,
            bind_context,
            reset_context,
            EngineContext,
            mission,
            boards[:1],
            -1,
        )
    except BudgetExhausted:
        pass
    else:
        raise AssertionError("spent budget did not time out")
    print("fields2cover cases ok")


def _call(plan, bind_context, reset_context, engine_context, mission, boards, budget_s: float):
    token = bind_context(engine_context(deadline=time.monotonic() + budget_s, boards=boards))
    try:
        return plan(mission)
    finally:
        reset_context(token)


def _mission(geo_mission, ring, boards: tuple, hole=None):
    symbols = geo_mission._core_symbols()
    obstacles = []
    if hole is not None:
        obstacles.append(
            symbols["Obstacle"](
                id="constraint-1",
                name="hole",
                height_m=0.0,
                polygon={"type": "Polygon", "coordinates": [list(hole)]},
            )
        )
    return symbols["MissionInput"](
        areas=[
            symbols["Area"](
                id="survey-1",
                name="survey-1",
                survey_type=symbols["SurveyType"]("visible"),
                polygon={"type": "Polygon", "coordinates": [list(ring)]},
            )
        ],
        obstacles=obstacles,
        vpps=[
            symbols["VPP"](
                id="аэродром 1",
                name="аэродром 1",
                lat=55.748,
                lon=37.604,
                alt_m=0.0,
                uavs=[board.uav_id for board in boards],
                cameras=["pf1b"],
            )
        ],
        uavs=[
            symbols["UAVConfig"](
                id=board.uav_id,
                model="gemini",
                camera_id="pf1b",
                vpp_id="аэродром 1",
            )
            for board in boards
        ],
        params=symbols["Params"](
            gsd_cm_per_px=2.0,
            wind=symbols["Wind"](speed_mps=1.0, direction_deg=90.0),
            optimization_criterion=symbols["Criterion"]("min_time"),
            overlap_x=0.5,
            overlap_long=0.6,
            angles_deg=[0.0],
            attempts_max=1,
            dem_file="unused.tif",
        ),
        dem=_Dem(100.0),
    )


def _board(uav_id: str, spacing_m: float, h_agl_m: float):
    from planes.runtime.fields2cover_engine import BoardCamera

    return BoardCamera(
        uav_id=uav_id,
        vpp_id="аэродром 1",
        lat=55.748,
        lon=37.604,
        endurance_s=2400.0,
        speed_m_s=15.0,
        spacing_m=spacing_m,
        h_agl_m=h_agl_m,
    )


def _pf1b() -> dict:
    return {
        "sensor_width_mm": {"value": 23.5},
        "focal_length_mm": {"value": 20},
        "image_width_px": {"value": 6000},
    }


if __name__ == "__main__":
    if os.environ.get("PLANES_F2C_CASES") == "1":
        _run_cases()
    else:
        unittest.main()
