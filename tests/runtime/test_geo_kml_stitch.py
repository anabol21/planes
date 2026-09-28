"""Survey and constraint KML reach the server, then the geo core.

The envelope solves on a flat plane. OpenTopography is not called.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

import numpy as np

from planes.integration.kml import parse_constraint_polygons, parse_survey_polygon
from planes.runtime.pipeline import run
from planes.runtime.solver import Problem, Solution, solve


_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SURVEY = (_FIXTURES / "stitch_survey.kml").read_text(encoding="utf-8")
_CONSTRAINTS = (_FIXTURES / "stitch_constraints.kml").read_text(encoding="utf-8")


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


def _local_xy(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    x = (lon - lon0) * 111_320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 110_540.0
    return x, y


def _crosses(route: list[dict], ring: list[list[float]]) -> bool:
    from shapely.geometry import LineString, Polygon

    lon0 = ring[0][0]
    lat0 = ring[0][1]
    obstacle = Polygon([_local_xy(lon, lat, lon0, lat0) for lon, lat in ring])
    line = LineString(
        [_local_xy(point["lon"], point["lat"], lon0, lat0) for point in route]
    )
    if line.is_empty or obstacle.is_empty:
        return False
    return line.intersection(obstacle).length > 0.5


class GeoKmlStitchTest(unittest.TestCase):
    def test_fixture_reaches_the_server_parser(self) -> None:
        survey = parse_survey_polygon(_SURVEY)
        polygons = parse_constraint_polygons(_CONSTRAINTS)
        self.assertEqual(len(survey), 1)
        ring = [[lon, lat] for lon, lat in survey[0].ring]
        self.assertEqual(ring[0], [37.6, 55.75])
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(polygons), 1)
        parsed = polygons[0].as_dict()
        self.assertEqual(parsed["name"], "Сектор А")
        self.assertEqual(parsed["type"], "врем_ограничение")
        self.assertEqual(parsed["altitudes_text"], "от 800 м AMSL до FL90")
        self.assertGreaterEqual(len(parsed["ring"]), 4)

    def test_missing_constraints_kml_calls_the_core_with_no_obstacles(self) -> None:
        from planes.runtime.geo_mission import _optional_text

        for missing in (None, "", "   "):
            self.assertEqual(parse_constraint_polygons(_optional_text(missing)), [])
        import planes.integration.terrain.opentopography as terrain

        calls: list[str] = []

        def opener(request, timeout=None):
            del timeout
            calls.append(request.full_url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            payload = _geotiff_bytes(
                float(query["west"][0]),
                float(query["south"][0]),
                float(query["east"][0]),
                float(query["north"][0]),
            )
            return _Body(payload)

        original = terrain.urllib.request.urlopen
        terrain.urllib.request.urlopen = opener
        cache = tempfile.mkdtemp(prefix="planes-terrain-empty-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test-key-not-a-secret"
        scenario = _scenario()
        del scenario["constraints_kml"]
        problem = Problem(
            job_id="job_stitch_no_constraints",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=60,
        )
        try:
            result = solve(problem, time.monotonic() + 60)
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(result.method, "pipeline")
            self.assertEqual(result.mission_plan["constraint_polygons"], [])
            self.assertEqual(result.mission_plan["obstacles"], [])
            self.assertTrue(result.mission_plan["routes"])
            self.assertEqual(calls, [])
            self.assertEqual(result.mission_plan["dem_file"], "mono")
        finally:
            terrain.urllib.request.urlopen = original
            if previous_cache is None:
                os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
            else:
                os.environ["PLANES_TERRAIN_CACHE_DIR"] = previous_cache
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key

    def test_two_survey_polygons_build_two_areas(self) -> None:
        import planes.integration.terrain.opentopography as terrain
        import planes.runtime.geo_mission as geo_mission

        survey = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>North</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.748,0 37.609,55.748,0 37.609,55.7525,0 37.601,55.7525,0 37.601,55.748,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>South</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.740,0 37.609,55.740,0 37.609,55.745,0 37.601,55.745,0 37.601,55.740,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""
        parsed = parse_survey_polygon(survey)
        self.assertEqual([polygon.name for polygon in parsed], ["North", "South"])

        def opener(request, timeout=None):
            del timeout
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            payload = _geotiff_bytes(
                float(query["west"][0]),
                float(query["south"][0]),
                float(query["east"][0]),
                float(query["north"][0]),
            )
            return _Body(payload)

        original_open = terrain.urllib.request.urlopen
        original_run = geo_mission._run_pipeline
        terrain.urllib.request.urlopen = opener
        seen: list[object] = []

        def run_pipeline(mission: object) -> object:
            seen.append(mission)
            return original_run(mission)

        geo_mission._run_pipeline = run_pipeline
        cache = tempfile.mkdtemp(prefix="planes-terrain-two-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test-key-not-a-secret"
        scenario = _scenario()
        scenario["survey_kml"] = survey
        del scenario["constraints_kml"]
        problem = Problem(
            job_id="job_stitch_two_areas",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=60,
        )
        try:
            result = solve(problem, time.monotonic() + 60)
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(len(seen), 1)
            areas = seen[0].areas
            self.assertEqual(len(areas), 2)
            self.assertEqual([area.name for area in areas], ["North", "South"])
            self.assertEqual(
                [area.polygon["coordinates"][0][0] for area in areas],
                [[37.601, 55.748], [37.601, 55.74]],
            )
            self.assertEqual(len(result.mission_plan["areas"]), 2)
            self.assertEqual(result.mission_plan["obstacles"], [])
        finally:
            geo_mission._run_pipeline = original_run
            terrain.urllib.request.urlopen = original_open
            if previous_cache is None:
                os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
            else:
                os.environ["PLANES_TERRAIN_CACHE_DIR"] = previous_cache
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key

    def test_bbox_requests_terrain_and_the_plan_avoids_constraints(self) -> None:
        import planes.integration.terrain.opentopography as terrain

        calls: list[str] = []

        def opener(request, timeout=None):
            del timeout
            calls.append(request.full_url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            payload = _geotiff_bytes(
                float(query["west"][0]),
                float(query["south"][0]),
                float(query["east"][0]),
                float(query["north"][0]),
            )
            return _Body(payload)

        original = terrain.urllib.request.urlopen
        terrain.urllib.request.urlopen = opener
        cache = tempfile.mkdtemp(prefix="planes-terrain-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test-key-not-a-secret"
        problem = Problem(
            job_id="job_stitch",
            scenario=_scenario(),
            objective="min_time",
            seed=7,
            time_limit_seconds=60,
        )
        try:
            result = solve(problem, time.monotonic() + 60)
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(result.method, "pipeline")
            self.assertEqual(result.mission_plan["dem_file"], "mono")
            self.assertEqual(calls, [])
            self.assertIn(
                "temporary flat terrain; OpenTopography was not called",
                result.limitations,
            )
            self.assertNotIn("test-key-not-a-secret", "\n".join(result.limitations))
            polygons = result.mission_plan["constraint_polygons"]
            self.assertEqual(polygons[0]["name"], "Сектор А")
            self.assertEqual(polygons[0]["altitudes_text"], "от 800 м AMSL до FL90")
            self.assertEqual(result.mission_plan["obstacles"][0]["height_m"], 0.0)
            self.assertTrue(result.mission_plan["routes"])
            for route in result.mission_plan["routes"]:
                self.assertFalse(
                    _crosses(route["waypoints"], polygons[0]["ring"]),
                    route["waypoints"],
                )
            again = solve(problem, time.monotonic() + 60)
            self.assertIsInstance(again, Solution)
            self.assertEqual(calls, [])
            self.assertEqual(again.mission_plan["dem_file"], "mono")
        finally:
            terrain.urllib.request.urlopen = original
            if previous_cache is None:
                os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
            else:
                os.environ["PLANES_TERRAIN_CACHE_DIR"] = previous_cache
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key

    def test_missing_api_key_uses_the_flat_stub(self) -> None:
        import planes.integration.terrain.opentopography as terrain

        def opener(request, timeout=None):
            del request, timeout
            raise AssertionError("missing key still called OpenTopography")

        original = terrain.urllib.request.urlopen
        terrain.urllib.request.urlopen = opener
        cache = tempfile.mkdtemp(prefix="planes-terrain-missing-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
        problem = Problem(
            job_id="job_stitch_key",
            scenario=_scenario(),
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        raw = {
            "contract_version": "v0",
            "job_id": "job_stitch_key",
            "scenario": _scenario(),
            "optimization": {"objective": "min_time", "time_limit_seconds": 30},
            "seed": 7,
        }
        try:
            result = solve(problem, time.monotonic() + 30)
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(result.mission_plan["dem_file"], "mono")
            self.assertIn(
                "temporary flat terrain; OpenTopography was not called",
                result.limitations,
            )
            import json

            response = run(json.dumps(raw).encode("utf-8"))
            self.assertEqual(response.outcome, "feasible")
            self.assertEqual(response.mission_plan["dem_file"], "mono")
            self.assertTrue(
                any(
                    item == "temporary flat terrain; OpenTopography was not called"
                    for item in response.solver_report.limitations
                )
            )
        finally:
            terrain.urllib.request.urlopen = original
            if previous_cache is None:
                os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
            else:
                os.environ["PLANES_TERRAIN_CACHE_DIR"] = previous_cache
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key

    def test_invalid_raster_uses_the_flat_stub(self) -> None:
        import planes.integration.terrain.opentopography as terrain

        def opener(request, timeout=None):
            del request, timeout
            return _Body(b"not-a-geotiff")

        original = terrain.urllib.request.urlopen
        terrain.urllib.request.urlopen = opener
        cache = tempfile.mkdtemp(prefix="planes-terrain-bad-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test-key-not-a-secret"
        problem = Problem(
            job_id="job_stitch_bad",
            scenario=_scenario(),
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        try:
            result = solve(problem, time.monotonic() + 30)
            self.assertIsInstance(result, Solution)
            assert isinstance(result, Solution)
            self.assertEqual(result.mission_plan["dem_file"], "mono")
            self.assertIn(
                "temporary flat terrain; OpenTopography was not called",
                result.limitations,
            )
        finally:
            terrain.urllib.request.urlopen = original
            if previous_cache is None:
                os.environ.pop("PLANES_TERRAIN_CACHE_DIR", None)
            else:
                os.environ["PLANES_TERRAIN_CACHE_DIR"] = previous_cache
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key

    def test_envelope_does_not_call_acquire_terrain_for_area(self) -> None:
        import planes.integration.terrain as terrain_pkg
        import planes.integration.terrain.opentopography as terrain
        import planes.runtime.geo_mission as geo_mission

        calls: list[str] = []

        def acquire(*args: object, **kwargs: object) -> str:
            del args, kwargs
            calls.append("acquire_terrain_for_area")
            raise AssertionError("acquire_terrain_for_area called")

        originals = {
            "module": terrain.acquire_terrain_for_area,
            "package": terrain_pkg.acquire_terrain_for_area,
        }
        bound = getattr(geo_mission, "acquire_terrain_for_area", None)
        terrain.acquire_terrain_for_area = acquire
        terrain_pkg.acquire_terrain_for_area = acquire
        if bound is not None:
            geo_mission.acquire_terrain_for_area = acquire
        previous_key = os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)

        def opener(request, timeout=None):
            del request, timeout
            raise AssertionError("OpenTopography was called")

        original_open = terrain.urllib.request.urlopen
        terrain.urllib.request.urlopen = opener
        problem = Problem(
            job_id="job_stitch_mono",
            scenario=_scenario(),
            objective="min_time",
            seed=7,
            time_limit_seconds=60,
        )
        try:
            result = solve(problem, time.monotonic() + 60)
        finally:
            terrain.acquire_terrain_for_area = originals["module"]
            terrain_pkg.acquire_terrain_for_area = originals["package"]
            if bound is not None:
                geo_mission.acquire_terrain_for_area = bound
            terrain.urllib.request.urlopen = original_open
            if previous_key is None:
                os.environ.pop("OPENTOPOGRAPHY_API_KEY", None)
            else:
                os.environ["OPENTOPOGRAPHY_API_KEY"] = previous_key
        self.assertEqual(calls, [])
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        self.assertEqual(result.mission_plan["dem_file"], "mono")
        self.assertFalse(Path(result.mission_plan["dem_file"]).is_absolute())
        self.assertIn(
            "temporary flat terrain; OpenTopography was not called",
            result.limitations,
        )
        for route in result.mission_plan["routes"]:
            points = route["waypoints"]
            self.assertEqual(points[0]["alt_m"], 0.0)
            self.assertEqual(points[-1]["alt_m"], 0.0)
            survey = [point["alt_m"] for point in points if point["alt_m"] != 0.0]
            self.assertTrue(survey)
            self.assertTrue(all(math.isclose(alt, survey[0]) for alt in survey))
            self.assertGreater(survey[0], 0.0)


if __name__ == "__main__":
    unittest.main()
