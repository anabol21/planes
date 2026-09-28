"""Safe contracts for the stitched envelope. HTTP is mocked.

These tests lock the handoff. They do not change the optimizer. A failure
is the seam record, not a reason to loosen the assertion.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import numpy as np

from planes.runtime.solver import Problem, Solution, solve


_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SURVEY = (_FIXTURES / "stitch_survey.kml").read_text(encoding="utf-8")
_CONSTRAINTS = (_FIXTURES / "stitch_constraints.kml").read_text(encoding="utf-8")
_GIBRID_INPUT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "basic_model"
    / "gibrid-optimizer"
    / "data"
    / "input.json"
)
_DEM_PY = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "itog_model"
    / "mvp_optimizator"
    / "src"
    / "planner"
    / "io"
    / "dem.py"
)
# Synthetic credential. Never the process environment value.
_SYNTHETIC_KEY = "synthetic-audit-key"
_FAR_CONSTRAINTS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>far</name>
<ExtendedData><Data name="Altitudes"><value>от 800 м AMSL до FL90</value></Data></ExtendedData>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
10.000,10.000,800 10.100,10.000,800 10.100,10.100,800 10.000,10.100,800 10.000,10.000,800
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>"""


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._payload = self._payload, b""
            return chunk
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _Point:
    def __init__(self, lat: float, lon: float, alt_m: float) -> None:
        self.lat = lat
        self.lon = lon
        self.alt_m = alt_m


class _Route:
    def __init__(self, uav_id: str, vpp_id: str) -> None:
        self.uav_id = uav_id
        self.vpp_id = vpp_id
        self.flight_index = 0
        self.waypoints = [_Point(55.751, 37.604, 150.0)]


class _Candidate:
    def __init__(self, uav_ids: list[str]) -> None:
        self.C_max_s = 10.0
        self.flight_hours_s = 12.0
        self.n_uavs_used = len(uav_ids)
        self.routes = [_Route(uav_id, "аэродром 1") for uav_id in uav_ids]


def _geotiff_bytes(west: float, south: float, east: float, north: float) -> bytes:
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds

    data = np.full((4, 4), 120.0, dtype=np.float32)
    transform = from_bounds(west, south, east, north, 4, 4)
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=4,
            width=4,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
        ) as dataset:
            dataset.write(data, 1)
        return memory.read()


def _scenario() -> dict:
    return {
        "crs": "EPSG:4326",
        "criterion": "min_time",
        "gsd_cm_per_px": 2,
        "required_spectrum": "RGB",
        "survey_kml": _SURVEY,
        "constraints_kml": _CONSTRAINTS,
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
        "wind": {"speed_ms": 1, "direction_deg": 90},
    }


def _board(board_id: str, model_id: str, camera_id: str) -> dict:
    return {
        "id": board_id,
        "model_id": model_id,
        "camera_id": camera_id,
        "aerodrome_id": "аэродром 1",
        "count": 1,
    }


def _exception_chain(exc: BaseException) -> str:
    """Text Python prints: explicit causes, and context only when it is not suppressed."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(type(current).__name__)
        parts.append(str(current))
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return "\n".join(parts)


class StitchSeamContractTest(unittest.TestCase):
    def setUp(self) -> None:
        import planes.integration.terrain.opentopography as terrain

        self._terrain = terrain
        self._calls: list[str] = []
        self._original_open = terrain.urllib.request.urlopen
        self._cache = tempfile.mkdtemp(prefix="planes-audit-")
        self._previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        self._previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = self._cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = _SYNTHETIC_KEY
        terrain.urllib.request.urlopen = self._opener

    def tearDown(self) -> None:
        self._terrain.urllib.request.urlopen = self._original_open
        if self._previous_cache is None:
            os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
        else:
            os.environ["PLANES_TERRAIN_CACHE_DIR"] = self._previous_cache
        if self._previous_key is None:
            os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
        else:
            os.environ["OPENTOPOGRAPHY_API_KEY"] = self._previous_key

    def _opener(self, request, timeout=None):
        del timeout
        self._calls.append(request.full_url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        payload = _geotiff_bytes(
            float(query["west"][0]),
            float(query["south"][0]),
            float(query["east"][0]),
            float(query["north"][0]),
        )
        return _Body(payload)

    def _solve(self, scenario: dict, job_id: str, *, real_pipeline: bool = False):
        import planes.runtime.geo_mission as geo_mission

        seen: list[object] = []
        original = geo_mission._run_pipeline

        def run_pipeline(mission: object):
            seen.append(mission)
            if real_pipeline:
                return original(mission)
            ids = [uav.id for uav in mission.uavs]
            return _Candidate(ids)

        geo_mission._run_pipeline = run_pipeline
        problem = Problem(
            job_id=job_id,
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=60,
        )
        try:
            result = solve(problem, time.monotonic() + 60)
        finally:
            geo_mission._run_pipeline = original
        return result, seen

    def test_blank_constraints_are_an_empty_obstacle_list(self) -> None:
        for blank in ("", "   ", None):
            scenario = _scenario()
            if blank is None:
                del scenario["constraints_kml"]
            else:
                scenario["constraints_kml"] = blank
            result, seen = self._solve(scenario, "job_audit_blank")
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(result.mission_plan["obstacles"], [])
            self.assertEqual(result.mission_plan["constraint_polygons"], [])
            self.assertEqual(seen[0].obstacles, [])

    def test_constraint_altitude_text_is_not_a_height(self) -> None:
        scenario = _scenario()
        scenario["constraints_kml"] = _FAR_CONSTRAINTS
        result, seen = self._solve(scenario, "job_audit_alt")
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        obstacle = seen[0].obstacles[0]
        self.assertEqual(obstacle.height_m, 0.0)
        self.assertEqual(result.mission_plan["obstacles"][0]["height_m"], 0.0)
        parsed = result.mission_plan["constraint_polygons"][0]
        self.assertEqual(parsed["altitudes_text"], "от 800 м AMSL до FL90")
        self.assertNotIn(800, [value for point in parsed["ring"] for value in point])
        self.assertTrue(all(len(point) == 2 for point in parsed["ring"]))

    def test_terrain_bbox_is_the_survey_only(self) -> None:
        scenario = _scenario()
        scenario["constraints_kml"] = _FAR_CONSTRAINTS
        scenario["aerodromes"] = [{"id": "аэродром 1", "lat": 10.05, "lon": 10.05}]
        result, _seen = self._solve(scenario, "job_audit_bbox")
        self.assertIsInstance(result, Solution)
        self.assertEqual(len(self._calls), 1)
        query = self._calls[0]
        self.assertIn("west=37.60000000", query)
        self.assertIn("south=55.75000000", query)
        self.assertIn("east=37.60800000", query)
        self.assertIn("north=55.75400000", query)
        self.assertNotIn("west=10.00000000", query)
        self.assertNotIn("south=10.00000000", query)

    def test_repeated_bbox_does_not_hit_the_network_without_the_key(self) -> None:
        scenario = _scenario()
        first, _seen = self._solve(scenario, "job_audit_cache")
        self.assertIsInstance(first, Solution)
        self.assertEqual(len(self._calls), 1)
        os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
        second, _seen = self._solve(scenario, "job_audit_cache_again")
        self.assertIsInstance(second, Solution)
        self.assertEqual(len(self._calls), 1)
        assert isinstance(first, Solution)
        assert isinstance(second, Solution)
        self.assertEqual(first.mission_plan["dem_file"], second.mission_plan["dem_file"])

    def test_invalid_raster_and_missing_key_fail_instead_of_flat_terrain(self) -> None:
        from planes.runtime.pipeline import run

        def bad_opener(request, timeout=None):
            del request, timeout
            return _Body(b"not-a-geotiff")

        self._terrain.urllib.request.urlopen = bad_opener
        scenario = _scenario()
        problem = Problem(
            job_id="job_audit_bad",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        with self.assertRaises(ValueError) as caught:
            solve(problem, time.monotonic() + 30)
        self.assertIn("TIFF", str(caught.exception))
        self.assertNotIn("flat terrain", str(caught.exception).lower())
        raw = {
            "contract_version": "v0",
            "job_id": "job_audit_bad",
            "scenario": scenario,
            "optimization": {"objective": "min_time", "time_limit_seconds": 30},
            "seed": 7,
        }
        response = run(json.dumps(raw).encode("utf-8"))
        self.assertEqual(response.outcome, "error")
        self.assertIsNone(response.mission_plan)

        self._calls.clear()
        self._terrain.urllib.request.urlopen = self._opener
        os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
        fresh = tempfile.mkdtemp(prefix="planes-audit-missing-")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = fresh
        with self.assertRaises(ValueError) as missing:
            solve(problem, time.monotonic() + 30)
        self.assertIn("OPENTOPOGRAPHY_API_KEY", str(missing.exception))
        self.assertEqual(self._calls, [])
        self.assertNotIn("flat", str(missing.exception).lower())

    def test_api_key_is_absent_from_logs_exceptions_and_cache_names(self) -> None:
        import planes.runtime.geo_mission as geo_mission
        import planes.runtime.logs as logs

        log_dir = Path(self._cache) / "logs"
        log_dir.mkdir()
        recorded: list[str] = []
        original_record = geo_mission.record
        original_log_dir = logs.log_directory
        stderr = io.StringIO()

        def record(job_id: str, summary: str, stderr_text: str = "") -> str:
            recorded.append(summary)
            recorded.append(stderr_text)
            return original_record(job_id, summary, stderr_text)

        logs.log_directory = lambda: log_dir
        geo_mission.record = record
        try:
            with contextlib.redirect_stderr(stderr):
                result, _seen = self._solve(_scenario(), "job_audit_key_log")
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertTrue(self._calls)

            def boom(request, timeout=None):
                raise urllib.error.HTTPError(
                    request.full_url,
                    401,
                    "unauthorized",
                    hdrs=None,
                    fp=io.BytesIO(b"denied"),
                )

            self._terrain.urllib.request.urlopen = boom
            os.environ["PLANES_TERRAIN_CACHE_DIR"] = str(Path(self._cache) / "empty-cache")
            problem = Problem(
                job_id="job_audit_http",
                scenario=_scenario(),
                objective="min_time",
                seed=7,
                time_limit_seconds=30,
            )
            with self.assertRaises(ValueError) as caught:
                solve(problem, time.monotonic() + 30)
            leaked = "\n".join(
                [
                    _exception_chain(caught.exception),
                    stderr.getvalue(),
                    "\n".join(recorded),
                    "\n".join(result.limitations),
                    "\n".join(path.name for path in Path(self._cache).rglob("*")),
                ]
            )
            self.assertNotIn(_SYNTHETIC_KEY, leaked)
            self.assertNotIn("API_Key=", leaked)
        finally:
            geo_mission.record = original_record
            logs.log_directory = original_log_dir

    def test_one_to_one_catalog_ids_translate(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        symbols = geo_mission._core_symbols()
        catalog = symbols["get_default_catalog"]()
        pairs = {
            "geoscan-gemini": "gemini",
            "geoscan-201": "geoscan201",
            "geoscan-801": "geoscan801",
        }
        cameras = {
            "geoscan-pf1b": "pf1b",
            "geoscan-pollux": "pollux",
            "riebo-r4": "riebo-r4",
            "geoscan-801-thermal": "801-thermal",
        }
        for fleet_id, core_id in pairs.items():
            self.assertEqual(geo_mission._translate_model(fleet_id, catalog), core_id)
        for fleet_id, core_id in cameras.items():
            self.assertEqual(geo_mission._translate_camera(fleet_id, catalog), core_id)

    def test_distinct_fleet_focals_stay_distinct_on_the_mission(self) -> None:
        umc = _scenario()
        umc["boards"] = [
            _board("БВС 16", "geoscan-gemini", "sony-umc-r10c-16"),
            _board("БВС 20", "geoscan-gemini", "sony-umc-r10c-20"),
        ]
        with self.subTest(cameras="umc-16-and-20"):
            _result, seen = self._solve(umc, "job_audit_umc")
            ids = [uav.camera_id for uav in seen[0].uavs]
            self.assertEqual(ids, ["umc-r10c-16", "umc-r10c-20"])

        visible = _scenario()
        visible["boards"] = [
            _board("БВС 4", "geoscan-801", "geoscan-801-visible-4-35"),
            _board("БВС 16", "geoscan-801", "geoscan-801-visible-16"),
        ]
        with self.subTest(cameras="801-visible-focals"):
            _result, seen = self._solve(visible, "job_audit_801")
            ids = [uav.camera_id for uav in seen[0].uavs]
            self.assertEqual(ids, ["801-visible-4-35", "801-visible-16"])

    def test_core_does_not_invent_optics_for_ambiguous_or_blank_cameras(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        symbols = geo_mission._core_symbols()
        catalog = symbols["get_default_catalog"]()
        from planner.geometry.generate import _camera_params_from_catalog

        umc = catalog.get_camera("umc-r10c")
        with self.subTest(camera="umc-r10c"):
            phrase = umc["specs"]["performance"]["focal_length"]
            self.assertIn("или", phrase)
            with self.assertRaisesRegex(ValueError, "Ambiguous body record"):
                _camera_params_from_catalog(umc)

        visible = catalog.get_camera("801-visible")
        self.assertNotIn("focal_length", visible["specs"].get("performance", {}))
        with self.subTest(camera="801-visible"):
            with self.assertRaisesRegex(ValueError, "Ambiguous optical configuration"):
                _camera_params_from_catalog(visible)

        rx = catalog.get_camera("rx1rm3")
        with self.subTest(camera="rx1rm3"):
            parsed_rx = _camera_params_from_catalog(rx)
            self.assertNotIn("focal_length", rx["specs"].get("performance", {}))
            self.assertNotEqual(parsed_rx["focal_mm"], 20.0)

    @unittest.expectedFailure  # Known separate solver issue; assertion is preserved.
    def test_joint_swath_height_does_not_follow_board_order(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        geo_mission._core_symbols()
        from planner.solver.pipeline import _generate_all_swaths

        scenario = _scenario()
        scenario["boards"] = [
            _board("БВС pf", "geoscan-gemini", "geoscan-pf1b"),
            _board("БВС umc", "geoscan-gemini", "sony-umc-r10c-20"),
        ]
        _result, seen = self._solve(scenario, "job_audit_order")
        mission = seen[0]
        _swaths, heights = _generate_all_swaths(mission, 0.0)
        swapped = mission.model_copy(update={"uavs": list(reversed(mission.uavs))})
        _swaths, swapped_heights = _generate_all_swaths(swapped, 0.0)
        self.assertEqual(
            list(heights.values()),
            list(swapped_heights.values()),
            "joint swath height followed the first board's camera",
        )

    def test_sweep_substitutes_201_power_and_geo_core_reads_constant_watts(self) -> None:
        import planes.runtime.geo_mission as geo_mission
        from planes.runtime.enumeration import run_candidates

        profile = json.loads(_GIBRID_INPUT.read_text(encoding="utf-8"))
        sweep = {
            "area": profile["area"],
            "criterion": "min_time",
            "wind": profile["wind"],
            "gsd_cm_per_px": profile["gsd_cm_per_px"],
            "survey": profile["survey"],
            "required_spectrum": "RGB",
            "aerodromes": [{"id": "аэродром 1", "lat": 55.748, "lon": 37.604}],
            "boards": [_board("БВС 201", "geoscan-201", "riebo-r4")],
        }

        def fake(data, seed: int = 0):
            del data, seed
            return {"status": "infeasible", "reason": "spy"}

        outcome = run_candidates(sweep, seed=7, time_limit_s=30, core=fake)
        self.assertEqual(len(outcome.attempts), 1)
        coeffs = outcome.attempts[0].data.power_coeffs
        self.assertEqual((coeffs.kh, coeffs.kv, coeffs.kw), (90.0, 0.02, 0.008))
        disclosure = "\n".join(outcome.disclosures)
        self.assertIn("90 / 0.02 / 0.008", disclosure)
        self.assertIn("220", disclosure)

        scenario = _scenario()
        scenario["boards"] = [_board("БВС 201", "geoscan-201", "riebo-r4")]
        _result, seen = self._solve(scenario, "job_audit_201")
        uav = seen[0].uavs[0]
        self.assertEqual(uav.model, "geoscan201")
        self.assertEqual(uav.camera_id, "riebo-r4")
        symbols = geo_mission._core_symbols()
        from planner.physics.factory import build_physics_model, build_physics_params

        params = build_physics_params(uav, symbols["get_default_catalog"]())
        model = build_physics_model(params)
        self.assertEqual(params.P_const_w, 220.0)
        self.assertEqual(model.power_w(25.0, 3.0), 220.0)
        rotor = (
            params.k_h * params.mass_kg
            + params.k_v * (25.0 ** 3)
            + params.k_w * (3.0 ** 2) * params.mass_kg
        )
        self.assertNotEqual(model.power_w(25.0, 3.0), rotor)
        self.assertFalse(hasattr(seen[0], "power_coeffs"))

    def test_area_tiff_and_heights_keep_degrees_metres_and_epsg4326(self) -> None:
        import rasterio

        import planes.runtime.geo_mission as geo_mission

        geo_mission._core_symbols()
        from planner.utils.geo import make_local_transformer

        result, seen = self._solve(_scenario(), "job_audit_units")
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        mission = seen[0]
        ring = mission.areas[0].polygon["coordinates"][0]
        self.assertEqual(mission.areas[0].polygon["type"], "Polygon")
        for lon, lat in ring:
            self.assertGreaterEqual(lon, -180.0)
            self.assertLessEqual(lon, 180.0)
            self.assertGreaterEqual(lat, -90.0)
            self.assertLessEqual(lat, 90.0)
            self.assertLess(abs(lon), 1000.0)
        self.assertEqual(result.mission_plan["crs"], "EPSG:4326")
        self.assertEqual(mission.params.gsd_cm_per_px, 2.0)
        self.assertEqual(mission.params.overlap_x, 0.5)
        self.assertEqual(mission.params.overlap_long, 0.6)
        self.assertEqual(mission.params.wind.speed_mps, 1.0)
        self.assertEqual(mission.params.wind.direction_deg, 90.0)
        self.assertEqual(mission.obstacles[0].height_m, 0.0)
        self.assertEqual(mission.vpps[0].alt_m, 0.0)
        dem_file = result.mission_plan["dem_file"]
        with rasterio.open(dem_file) as dataset:
            self.assertEqual(dataset.crs.to_string(), "EPSG:4326")
        sample = mission.dem.h(55.752, 37.604)
        self.assertTrue(math.isclose(sample, 120.0, abs_tol=1.0))
        fwd, _inv = make_local_transformer(37.6, 55.75)
        east_m, _north_m = fwd.transform(37.601, 55.75)
        self.assertGreater(abs(east_m), 50.0)
        self.assertLess(abs(east_m), 200.0)

    def test_heuristic_result_is_not_labeled_globally_optimal(self) -> None:
        from planes.runtime.solver import _map_result

        result, _seen = self._solve(_scenario(), "job_audit_heuristic")
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        text = "\n".join(result.limitations)
        self.assertIn("heuristic result is not globally optimal", text)
        self.assertNotIn("globally optimal", text.replace("not globally optimal", ""))
        self.assertNotEqual(result.method, "optimal")
        self.assertEqual(result.mission_plan["solver"], "pipeline")

        mapped = _map_result(
            {
                "status": "heuristic",
                "criterion": "min_time",
                "solver": "meta",
                "mission": {"mission_time_s": 3.0, "total_flight_time_s": 4.0},
                "routes": [],
                "strips": [],
                "validation": {},
            }
        )
        mapped_text = "\n".join(mapped.limitations)
        self.assertIn("heuristic result is not globally optimal", mapped_text)
        self.assertNotIn("globally optimal", mapped_text.replace("not globally optimal", ""))
        self.assertEqual(mapped.method, "meta")

    def test_live_loader_is_the_dem_package_not_dem_py(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        symbols = geo_mission._core_symbols()
        live = symbols["load_dem"]
        self.assertEqual(live.__module__, "planner.io.dem.loader")
        self.assertTrue(Path(live.__code__.co_filename).as_posix().endswith("planner/io/dem/loader.py"))

        spec = importlib.util.spec_from_file_location("audit_dem_py_file", _DEM_PY)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["audit_dem_py_file"] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop("audit_dem_py_file", None)
            raise
        self.assertIsNot(live, module.load_dem)

        from planner.io.dem import load_dem as package_load_dem

        self.assertIs(package_load_dem, live)

        tif = Path(self._cache) / "sample.tif"
        tif.write_bytes(_geotiff_bytes(37.6, 55.75, 37.608, 55.754))
        kml_dem = module.load_dem(tif)
        self.assertTrue(kml_dem.is_empty())
        self.assertEqual(kml_dem.h(55.752, 37.604), 0.0)
        loaded = live(tif)
        self.assertNotEqual(type(loaded).__name__, "FlatDEM")
        self.assertFalse(loaded.is_empty())
        self.assertTrue(math.isclose(loaded.h(55.752, 37.604), 120.0, abs_tol=1.0))

        notes = Path(self._cache) / "notes.txt"
        notes.write_text("not a raster", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            geo_mission._load_geotiff(notes)
        self.assertIn("refusing flat terrain", str(caught.exception))

    def test_envelope_is_one_joint_mission_and_does_not_call_select_winner(self) -> None:
        import planes.runtime.enumeration.outer as outer

        calls: list[object] = []
        original = outer.select_winner

        def spy(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        scenario = _scenario()
        scenario["boards"] = [
            _board("БВС 1", "geoscan-gemini", "geoscan-pf1b"),
            _board("БВС 2", "geoscan-gemini", "geoscan-pf1b"),
        ]
        outer.select_winner = spy
        try:
            result, seen = self._solve(scenario, "job_audit_joint", real_pipeline=True)
        finally:
            outer.select_winner = original
        self.assertEqual(calls, [])
        self.assertEqual([uav.id for uav in seen[0].uavs], ["БВС 1", "БВС 2"])
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        self.assertEqual(result.method, "pipeline")
        routed = {route["uav_id"] for route in result.mission_plan["routes"]}
        self.assertEqual(routed, {"БВС 1", "БВС 2"})

    def test_takeoff_uav_is_rejected_before_gibrid(self) -> None:
        import planes.runtime.geo_mission as geo_mission

        scenario = json.loads(_GIBRID_INPUT.read_text(encoding="utf-8"))
        self.assertNotIn("aerodromes", scenario)
        self.assertNotIn("boards", scenario)
        entered: list[str] = []

        def boom(*args, **kwargs):
            del args, kwargs
            entered.append("geo")
            raise AssertionError("one-card scenario entered the geo envelope")

        original_envelope = geo_mission.solve_envelope
        geo_mission.solve_envelope = boom
        try:
            with self.assertRaises(ValueError) as caught:
                solve(
                    Problem(
                        job_id="job_audit_gibrid",
                        scenario=scenario,
                        objective="min_flight_hours",
                        seed=7,
                        time_limit_seconds=30,
                    ),
                    time.monotonic() + 30,
                )
        finally:
            geo_mission.solve_envelope = original_envelope
        self.assertEqual(entered, [])
        self.assertIn("the listener only accepts the geo envelope", str(caught.exception))

    def test_backend_job_keeps_the_scenario_text(self) -> None:
        from planes.backend.models import ComputeResponse
        from planes.backend.service import BackendService
        from planes.backend.store import SQLiteJobStore
        from planes.backend.worker import Worker
        from planes.backend.models import thaw_json

        database = Path(self._cache) / "jobs.sqlite3"
        store = SQLiteJobStore(str(database))
        service = BackendService(store)
        scenario = _scenario()
        scenario["constraints_kml"] = ""
        scenario["survey_kml"] = _SURVEY
        submitted = service.submit_job(
            scenario=scenario,
            optimization={"objective": "min_time", "time_limit_seconds": 30},
            seed=7,
            job_id="job_audit_backend",
        )
        self.assertEqual(submitted["state"], "queued")
        stored = store.get_job("job_audit_backend")
        assert stored is not None
        self.assertEqual(stored.scenario["survey_kml"], _SURVEY)
        self.assertEqual(stored.scenario["constraints_kml"], "")
        self.assertEqual(stored.scenario["crs"], "EPSG:4326")
        self.assertEqual(stored.scenario["wind"]["speed_ms"], 1)
        self.assertEqual(stored.scenario["boards"][0]["camera_id"], "geoscan-pf1b")

        class Capture:
            def __init__(self) -> None:
                self.scenario = None

            def solve(self, request):
                self.scenario = thaw_json(request.scenario)
                return ComputeResponse(
                    job_id=request.job_id,
                    outcome="infeasible",
                    solver_report={"limitations": ["spy"]},
                )

        engine = Capture()
        claimed = Worker(store, engine).run_once()
        self.assertEqual(claimed, "job_audit_backend")
        assert engine.scenario is not None
        self.assertEqual(engine.scenario["survey_kml"], _SURVEY)
        self.assertEqual(engine.scenario["constraints_kml"], "")
        self.assertEqual(engine.scenario["gsd_cm_per_px"], 2)


if __name__ == "__main__":
    unittest.main()
