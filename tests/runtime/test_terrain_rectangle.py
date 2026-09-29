"""Canonical terrain, generated GeoTIFF and production ISO consumption. No network.

Run with PYTHONPATH=src python -B -m unittest discover -s tests/runtime
-p test_terrain_rectangle.py -v. Full subprocess solve additionally needs
F2C_EMBED_PYTHON (fields2cover 2.1.0, ortools, rasterio, numpy, shapely).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import urllib.parse
from unittest.mock import patch

from planes.integration.terrain import opentopography as terrain
from planes.integration.terrain.iso_acquire import ensure_dem_for_iso_scenario
from planes.runtime import grisha_f2c_bridge as bridge
from planes.runtime.interest_box import interest_rectangle, rectangle_geometry
from planes.runtime.solver import Problem, Solution

REPO = Path(__file__).resolve().parents[2]
HAS_RASTER = all(importlib.util.find_spec(name) for name in ("numpy", "rasterio"))


def scenario():
    return {
        "crs": "EPSG:4326", "criterion": "min_time", "required_spectrum": "RGB",
        "gsd_cm_per_px": 2, "survey": {"side_overlap": 0.5, "forward_overlap": 0.6},
        "wind": {"speed_ms": 0, "direction_deg": 0},
        "survey_kml": """<kml><Placemark><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>37.60,55.75 37.70,55.75 37.70,55.85 37.60,55.85 37.60,55.75</coordinates>
        </LinearRing></outerBoundaryIs></Polygon></Placemark>
        <Placemark><LineString><coordinates>1,1 2,2</coordinates></LineString></Placemark></kml>""",
        "constraints_kml": """<kml><Placemark><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>10,10 10.1,10 10.1,10.1 10,10</coordinates>
        </LinearRing></outerBoundaryIs></Polygon></Placemark></kml>""",
        "aerodromes": [{"id": "pad", "lon": 37.80, "lat": 55.70}],
        "boards": [{"id": "board", "model_id": "geoscan-gemini", "camera_id": "geoscan-pf1b",
                    "aerodrome_id": "pad", "count": 1}],
    }


class CaptureClient:
    def __init__(self):
        self.request = None

    def solve(self, request, **kwargs):
        self.request = request
        return {"outcome": "feasible", "mission_plan": {"mission": {"mission_time_s": 12}}}


def load_worker():
    path = REPO / "tools/f2c_iso/f2c_isolated_worker.py"
    spec = importlib.util.spec_from_file_location("terrain_worker_under_test", path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through the module registry.
    sys.modules[spec.name] = module
    with patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module


def raster_bytes(bounds, *, heights=None):
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    data = np.array(heights if heights is not None else [[100, 200], [300, 400]], dtype="float32")
    height, width = data.shape
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=1,
                      dtype="float32", crs="EPSG:4326",
                      transform=from_bounds(bounds.west, bounds.south, bounds.east, bounds.north, width, height)) as ds:
            ds.write(data, 1)
        return mem.read()


class CanonicalTest(unittest.TestCase):
    def test_actual_downloader_query_and_cache_identity_without_raster(self):
        geometry = bridge._canonical_terrain_geometry(scenario())
        expected = terrain.bbox_from_geojson(geometry, crs="EPSG:4326")
        queries = []
        validated = []

        def opener(request, **kwargs):
            parsed = urllib.parse.urlsplit(request.full_url)
            queries.append({k: v for k, v in urllib.parse.parse_qs(parsed.query).items() if k != "API_Key"})
            return io.BytesIO(b"II*\x00controlled downloader bytes")

        def validate(path, bounds):
            validated.append(bounds)
            self.assertEqual(bounds, expected)
            self.assertTrue(path.is_file())

        with tempfile.TemporaryDirectory(prefix="planes-query-") as cache, patch.dict(
            os.environ, {"OPENTOPOGRAPHY_API_KEY": "test-key-not-a-secret"}
        ), patch.object(terrain, "_validate_geotiff", validate):
            path = terrain.acquire_terrain_for_area(
                geometry, survey_crs="EPSG:4326", padding_m=0,
                cache_dir=cache, opener=opener,
            )
            again = terrain.acquire_terrain_for_area(
                geometry, survey_crs="EPSG:4326", padding_m=0,
                cache_dir=cache, opener=opener,
            )
            self.assertEqual(path, again)
        self.assertEqual(queries, [{
            "demtype": ["COP30"], "west": ["37.60000000"],
            "south": ["55.70000000"], "east": ["37.80000000"],
            "north": ["55.85000000"], "outputFormat": ["GTiff"],
        }])
        material = "COP30|37.60000000|55.70000000|37.80000000|55.85000000"
        digest = hashlib.sha256(material.encode("ascii")).hexdigest()[:24]
        self.assertEqual(path.name, f"COP30_{digest}.tif")
        self.assertEqual(validated, [expected, expected])

    def test_builder_inputs_are_survey_and_all_aerodromes(self):
        s = scenario()
        with patch("planes.runtime.interest_box.interest_rectangle", wraps=interest_rectangle) as builder:
            geometry = bridge._canonical_terrain_geometry(s)
        bounds = terrain.bbox_from_geojson(geometry, crs="EPSG:4326")
        self.assertEqual(bounds.normalized(), ("37.60000000", "55.70000000", "37.80000000", "55.85000000"))
        self.assertEqual(builder.call_count, 1)
        s["constraints_kml"] = None
        self.assertEqual(geometry, bridge._canonical_terrain_geometry(s))
        s["aerodromes"].append({"id": "far", "lon": 37.9, "lat": 55.6})
        expanded = terrain.bbox_from_geojson(bridge._canonical_terrain_geometry(s), crs="EPSG:4326")
        self.assertEqual((expanded.east, expanded.south), (37.9, 55.6))

    def test_multiple_areas_use_existing_builder(self):
        s = scenario()
        del s["survey_kml"]
        s["areas"] = [{"polygon": rectangle_geometry(interest_rectangle([[(37.6, 55.75), (37.7, 55.85)]], []))},
                      {"polygon": rectangle_geometry(interest_rectangle([[(37.5, 55.8), (37.6, 55.9)]], []))}]
        bounds = terrain.bbox_from_geojson(bridge._canonical_terrain_geometry(s), crs="EPSG:4326")
        self.assertEqual((bounds.west, bounds.south, bounds.east, bounds.north), (37.5, 55.7, 37.8, 55.9))

    def test_live_bridge_zero_padding_handoff_and_snapshot_preserved(self):
        s = scenario()
        original = copy.deepcopy(s)
        client = CaptureClient()
        calls = []
        def acquire(area, **kwargs):
            calls.append((area, kwargs))
            return Path("COP30_controlled.tif")
        with patch.dict(os.environ, {"PLANES_DEM_PADDING_M": "200"}), patch(
            "planes.integration.terrain.iso_acquire.acquire_terrain_for_area", acquire
        ), patch.object(bridge, "_load_client", return_value=client):
            result = bridge.solve_via_isolated_grisha_f2c(Problem("rect", s, "min_time", 7, 30), time.monotonic() + 30)
        self.assertIsInstance(result, Solution)
        self.assertEqual(calls[0][1]["padding_m"], 0)
        self.assertEqual(calls[0][0], bridge._canonical_terrain_geometry(s))
        self.assertEqual(client.request["scenario"]["dem_file"], "COP30_controlled.tif")
        self.assertEqual(client.request["scenario"]["constraints_kml"], s["constraints_kml"])
        self.assertEqual(s, original)

    def test_invalid_aerodromes_and_crs_fail_closed(self):
        for value in (float("nan"), 181, True, "37.8", None):
            s = scenario()
            s["aerodromes"][0]["lon"] = value
            with self.subTest(value=value), patch.dict(os.environ, {"PLANES_DEM_FAIL_CLOSED": "1"}):
                with self.assertRaises(terrain.TerrainAcquisitionError):
                    ensure_dem_for_iso_scenario(s, geometry_factory=bridge._canonical_terrain_geometry)
        s = scenario()
        s["crs"] = "EPSG:3857"
        with self.assertRaises(ValueError):
            bridge._canonical_terrain_geometry(s)

    def test_production_route_samples_dem_for_waypoint_asl(self):
        worker = load_worker()
        engine = sys.modules["fields2cover_engine_iso"]
        class KnownSurface:
            def h(self, lat, lon):
                return 180.0 if lon < 37.605 else 230.0
        lat, lon = 55.8, 37.6
        board = engine.BoardCamera("uav", "pad", lat, lon, 10000, 25, 30, 120)
        swath = engine._SwathEnds(engine._project(lon, lat, lon, lat),
                                  engine._project(37.61, lat, lon, lat), 100)
        route = engine._route(SimpleNamespace(dem=KnownSurface()), board, 1,
                              [swath], 12.0, lon, lat, [])
        self.assertEqual(route.waypoints[1].alt_m, 300.0)
        self.assertEqual(route.waypoints[2].alt_m, 350.0)
        self.assertEqual(route.T_total_s, 12.0)


@unittest.skipUnless(HAS_RASTER, "rasterio/numpy required for actual GeoTIFF tests")
class GeoTiffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="planes-rect-")
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"OPENTOPOGRAPHY_API_KEY": "test-key-not-a-secret",
                                         "PLANES_DEM_FAIL_CLOSED": "1", "PLANES_DEM_CACHE": self.tmp.name,
                                         "PLANES_DEM_PADDING_M": "200"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.expected = terrain.bbox_from_geojson(bridge._canonical_terrain_geometry(scenario()), crs="EPSG:4326")
        self.queries = []

    def opener(self, request, **kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.queries.append({k: v for k, v in query.items() if k != "API_Key"})
        b = terrain.SurveyBounds(*(float(query[k][0]) for k in ("west", "south", "east", "north")))
        return io.BytesIO(raster_bytes(b))

    def acquire(self):
        with patch.object(terrain.urllib.request, "urlopen", self.opener):
            out, notes = ensure_dem_for_iso_scenario(scenario(), geometry_factory=bridge._canonical_terrain_geometry)
        return Path(out["dem_file"]), notes

    def test_exact_query_cache_key_validation_and_cache_hit(self):
        validations = []
        validate = terrain._validate_geotiff
        def observed(path, bounds):
            validations.append(bounds)
            return validate(path, bounds)
        with patch.object(terrain, "_validate_geotiff", observed):
            path, notes = self.acquire()
            again, _ = self.acquire()
        self.assertEqual(self.queries, [{"demtype": ["COP30"], "west": ["37.60000000"],
            "south": ["55.70000000"], "east": ["37.80000000"], "north": ["55.85000000"], "outputFormat": ["GTiff"]}])
        digest = hashlib.sha256("COP30|37.60000000|55.70000000|37.80000000|55.85000000".encode("ascii")).hexdigest()[:24]
        self.assertEqual(path.name, f"COP30_{digest}.tif")
        self.assertEqual(path, again)
        self.assertEqual(validations, [self.expected, self.expected])
        self.assertFalse(any("mono" in note for note in notes))

    def test_partial_coverage_rejected_on_download_and_cache(self):
        partial = terrain.SurveyBounds(37.65, 55.7, 37.8, 55.85)
        with patch.object(terrain.urllib.request, "urlopen", return_value=io.BytesIO(raster_bytes(partial))):
            with self.assertRaisesRegex(terrain.TerrainAcquisitionError, "cover"):
                ensure_dem_for_iso_scenario(scenario(), geometry_factory=bridge._canonical_terrain_geometry)
        cached = terrain._cache_path(self.expected, Path(self.tmp.name))
        cached.write_bytes(raster_bytes(partial))
        with patch.object(terrain.urllib.request, "urlopen", side_effect=AssertionError("cached invalid raster must not use network")):
            with self.assertRaisesRegex(terrain.TerrainAcquisitionError, "cover"):
                ensure_dem_for_iso_scenario(scenario(), geometry_factory=bridge._canonical_terrain_geometry)

    def test_malformed_geotiff_fail_closed_and_distinct_mono_fallback(self):
        for fail_closed in ("1", "0"):
            with self.subTest(fail_closed=fail_closed), patch.dict(os.environ, {"PLANES_DEM_FAIL_CLOSED": fail_closed}), patch.object(
                terrain.urllib.request, "urlopen", return_value=io.BytesIO(b"not-a-tiff")
            ):
                if fail_closed == "1":
                    with self.assertRaisesRegex(terrain.TerrainAcquisitionError, "TIFF"):
                        ensure_dem_for_iso_scenario(scenario(), geometry_factory=bridge._canonical_terrain_geometry)
                else:
                    out, notes = ensure_dem_for_iso_scenario(scenario(), geometry_factory=bridge._canonical_terrain_geometry)
                    self.assertNotIn("dem_file", out)
                    self.assertTrue(any("dem_file: mono" in note for note in notes))

    def test_existing_dem_reused_without_download(self):
        path, _ = self.acquire()
        with patch.object(terrain.urllib.request, "urlopen", side_effect=AssertionError("reuse must not download")):
            out, notes = ensure_dem_for_iso_scenario(scenario() | {"dem_file": str(path)}, geometry_factory=bridge._canonical_terrain_geometry)
        self.assertEqual(Path(out["dem_file"]), path.resolve())
        self.assertTrue(any("existing readable" in note for note in notes))

    def test_worker_loader_and_production_route_altitudes(self):
        path, _ = self.acquire()
        worker = load_worker()
        dem, label, _ = worker._load_mission_dem({"dem_file": str(path)})
        self.assertIsInstance(dem, worker._GeoTiffDem)
        self.assertFalse(dem.is_empty())
        self.assertNotEqual(label, "mono")
        # Interior raster locations: top-left sample=100, next column=200.
        lat = 55.85 - (55.85 - 55.7) * 0.25
        lon_a, lon_b = 37.6, 37.7
        self.assertAlmostEqual(dem.h(lat, lon_a), 200)
        self.assertAlmostEqual(dem.h(lat, lon_b), 300)
        engine = sys.modules["fields2cover_engine_iso"]
        board = engine.BoardCamera("uav", "pad", lat, lon_a, 10000, 25, 30, 120)
        ends = engine._SwathEnds(engine._project(lon_a, lat, lon_a, lat),
                                 engine._project(lon_b, lat, lon_a, lat), 100)
        route = engine._route(SimpleNamespace(dem=dem), board, 1, [ends], 12.0, lon_a, lat, [])
        self.assertAlmostEqual(route.waypoints[1].alt_m, 320)
        self.assertAlmostEqual(route.waypoints[2].alt_m, 420)
        self.assertEqual(route.T_total_s, 12.0)

    @unittest.skipUnless(os.environ.get("F2C_EMBED_PYTHON"), "compatible F2C_EMBED_PYTHON required for full isolated solve")
    def test_controlled_download_bridge_isolated_worker_plan(self):
        # Small survey, all coordinates safely inside the synthetic raster.
        s = scenario()
        s["survey_kml"] = s["survey_kml"].replace("37.70", "37.602").replace("55.85", "55.752")
        s["aerodromes"][0].update(lon=37.603, lat=55.749)
        s["constraints_kml"] = None
        with patch.object(terrain.urllib.request, "urlopen", self.opener):
            result = bridge.solve_via_isolated_grisha_f2c(Problem("terrain-e2e", s, "min_time", 7, 30), time.monotonic() + 30)
        self.assertIsInstance(result, Solution)
        plan = result.mission_plan
        self.assertNotEqual(plan["dem_file"], "mono")
        worker = load_worker()
        dem = worker._GeoTiffDem(plan["dem_file"])
        self.assertFalse(dem.is_empty())
        b = terrain.bbox_from_geojson(bridge._canonical_terrain_geometry(s), crs="EPSG:4326")
        _, boards = worker._expand_boards(s, worker._load_catalog())
        agl = boards[0].h_agl_m
        samples = []
        for route in plan["routes"]:
            for wp in route["waypoints"][1:-1]:
                self.assertTrue(b.west <= wp["lon"] <= b.east and b.south <= wp["lat"] <= b.north)
                sample = dem.h(wp["lat"], wp["lon"])
                self.assertGreater(sample, 0)
                # Link waypoints may copy a neighbouring altitude; sampled
                # swath waypoints must reflect the terrain at their own XY.
                if abs(wp["alt_m"] - (sample + agl)) <= 0.02:
                    samples.append(sample)
        self.assertGreater(len(samples), 1)
        self.assertGreater(max(samples) - min(samples), 1)
        self.assertFalse(any("dem_file: mono" in note for note in result.limitations))


if __name__ == "__main__":
    unittest.main()
