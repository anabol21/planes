"""Opt-in real COP30 → isolated Linux Fields2Cover mission acceptance.

Run only with PLANES_RUN_REAL_TERRAIN_E2E=1, a real OpenTopography key,
and F2C_EMBED_PYTHON pointing at a Linux Fields2Cover 2.1.0 environment.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from planes.integration.terrain import opentopography as terrain
from planes.runtime import grisha_f2c_bridge as bridge
from planes.runtime.solver import Problem, Solution


REPO = Path(__file__).resolve().parents[2]
CLIENT = (REPO / "tools/f2c_iso/f2c_isolated_client.py").resolve()


def _scenario() -> dict:
    # The pad fixes the southern/eastern edges of the proven ~0.174 km² bbox.
    return {
        "crs": "EPSG:4326", "criterion": "min_time", "required_spectrum": "RGB",
        "gsd_cm_per_px": 2, "survey": {"side_overlap": 0.5, "forward_overlap": 0.6},
        "wind": {"speed_ms": 0, "direction_deg": 0},
        "survey_kml": (
            "<kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>"
            "37.600,55.750 37.604,55.750 37.604,55.754 "
            "37.600,55.754 37.600,55.750"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"
        ),
        "aerodromes": [{"id": "pad", "lon": 37.605, "lat": 55.749}],
        "boards": [{"id": "board", "model_id": "geoscan-gemini",
                    "camera_id": "geoscan-pf1b", "aerodrome_id": "pad", "count": 1}],
    }


def _worker_module():
    path = REPO / "tools/f2c_iso/f2c_isolated_worker.py"
    spec = importlib.util.spec_from_file_location("real_terrain_worker_for_dem_read", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.environ.get("PLANES_RUN_REAL_TERRAIN_E2E") == "1",
                     "explicit real terrain E2E opt-in required")
class RealTerrainE2E(unittest.TestCase):
    def test_real_cop30_drives_isolated_f2c_plan(self):
        self.assertTrue(os.environ.get("OPENTOPOGRAPHY_API_KEY"), "real API key required")
        embed = Path(os.environ["F2C_EMBED_PYTHON"]).resolve()
        self.assertTrue(embed.is_file(), "real Linux F2C Python required")
        self.assertNotEqual(os.name, "nt", "real F2C acceptance requires Linux")
        scenario = _scenario()
        self.assertNotIn("dem_file", scenario)
        canonical = terrain.bbox_from_geojson(
            bridge._canonical_terrain_geometry(scenario), crs="EPSG:4326"
        )
        self.assertEqual(canonical.normalized(),
                         ("37.60000000", "55.74900000", "37.60500000", "55.75400000"))
        self.assertEqual(terrain.COP30_GRID_ARCSEC, 1.0)
        guarded = terrain.cop30_request_bounds(canonical)
        self.assertEqual(guarded.normalized(),
                         ("37.59972222", "55.74872222", "37.60527778", "55.75427778"))

        # Observe the unmodified production client's return. Python profiling
        # sees the actual subprocess response without replacing client/worker.
        observed = []
        previous_profile = sys.getprofile()

        def observe(frame, event, value):
            if (event == "return" and frame.f_code.co_name == "solve"
                    and Path(frame.f_code.co_filename).resolve() == CLIENT):
                observed.append(value)

        with tempfile.TemporaryDirectory(prefix="planes-real-terrain-") as cache:
            with patch.dict(os.environ, {"PLANES_DEM_CACHE": cache,
                                         "PLANES_DEM_FAIL_CLOSED": "1"}):
                try:
                    sys.setprofile(observe)
                    result = bridge.solve_via_isolated_grisha_f2c(
                        Problem("terrain-real-e2e", scenario, "min_time", 7, 180),
                        time.monotonic() + 180,
                    )
                finally:
                    sys.setprofile(previous_profile)

                self.assertEqual(len(observed), 1, "production client subprocess must run once")
                raw = observed[0]
                self.assertEqual(raw.get("outcome"), "feasible", raw.get("error"))
                self.assertIsInstance(result, Solution)
                self.assertEqual(Path(raw["embed_python"]).resolve(), embed)
                isolation = raw["isolation"]
                self.assertEqual(Path(isolation["python"]).resolve(), embed)
                self.assertEqual(isolation["fields2cover_version"], "2.1.0")
                self.assertTrue(isolation["ortools_ok"])
                self.assertFalse(isolation["mvp_on_path"])
                self.assertFalse(isolation["grisha_sitecustomize"])

                plan = result.mission_plan
                self.assertEqual(raw["mission_plan"]["dem_file"], plan["dem_file"])
                self.assertNotEqual(plan["dem_file"], "mono")
                dem_path = Path(plan["dem_file"])
                self.assertEqual(dem_path.parent.resolve(), Path(cache).resolve())
                self.assertTrue(dem_path.is_file())
                terrain._validate_geotiff(dem_path, canonical)
                import numpy as np
                import rasterio
                with rasterio.open(dem_path) as raster:
                    self.assertEqual(raster.crs.to_string(), "EPSG:4326")
                    values = raster.read(1, masked=True).compressed()
                    finite = int(np.isfinite(values).sum())
                    self.assertGreater(finite, 0)
                    raster_bounds = list(raster.bounds)
                    raster_size = [raster.width, raster.height]

                # A cache hit must not invoke the opener. The first solve used
                # the production urllib path without any network interception.
                def reject_network(*_args, **_kwargs):
                    self.fail("cache reuse called the network")

                again = terrain.acquire_terrain_for_area(
                    bridge._canonical_terrain_geometry(scenario), survey_crs="EPSG:4326",
                    padding_m=0, cache_dir=cache, opener=reject_network,
                )
                self.assertEqual(again, dem_path)

                worker = _worker_module()
                dem = worker._GeoTiffDem(dem_path)
                self.assertFalse(dem.is_empty())
                _, boards = worker._expand_boards(scenario, worker._load_catalog())
                agl = boards[0].h_agl_m
                self.assertAlmostEqual(agl, plan["board_optics"][0]["h_agl_m"])
                routes = plan["routes"]
                self.assertGreater(len(routes), 0)
                waypoints = sum(len(route["waypoints"]) for route in routes)
                validated = []
                for route in routes:
                    # With no constraints, inner waypoints are survey swath ends.
                    for wp in route["waypoints"][1:-1]:
                        if not (37.600 <= wp["lon"] <= 37.604
                                and 55.750 <= wp["lat"] <= 55.754):
                            continue
                        ground = dem.h(wp["lat"], wp["lon"])
                        expected = ground + agl
                        if abs(wp["alt_m"] - expected) <= 0.02:
                            validated.append((wp, ground, expected))
                self.assertGreaterEqual(len(validated), 2)
                pair = next(((a, b) for a in validated for b in validated
                             if abs(a[1] - b[1]) > 1.0), None)
                self.assertIsNotNone(pair, "two swath waypoints need different real terrain")
                a, b = pair
                self.assertFalse(any("dem_file: mono" in note for note in result.limitations))
                self.assertFalse(plan["validation"]["climb_model_applied"])

                report = {
                    "canonical_bounds": canonical.normalized(),
                    "cop30_guard_arcsec": terrain.COP30_GRID_ARCSEC,
                    "request_bounds": guarded.normalized(),
                    "returned_tiff_bounds": raster_bounds,
                    "raster_size": raster_size,
                    "finite_elevations": finite,
                    "full_canonical_coverage": "PASS",
                    "cache_reuse": "PASS",
                    "child_python": isolation["python"],
                    "fields2cover_version": isolation["fields2cover_version"],
                    "child_outcome": raw["outcome"],
                    "solver_method": result.method,
                    "dem_file": str(dem_path),
                    "mono_fallback": "NO",
                    "routes": len(routes),
                    "waypoints": waypoints,
                    "validated_survey_waypoints": len(validated),
                    "h_agl_m": agl,
                    "sample_a": {"dem_m": a[1], "waypoint_alt_m": a[0]["alt_m"],
                                 "expected_alt_m": a[2]},
                    "sample_b": {"dem_m": b[1], "waypoint_alt_m": b[0]["alt_m"],
                                 "expected_alt_m": b[2]},
                    "duration_model": "2D unchanged",
                }
                report_path = os.environ.get("PLANES_TERRAIN_E2E_REPORT")
                if report_path:
                    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print("REAL TERRAIN E2E REPORT = " + json.dumps(report, sort_keys=True))
