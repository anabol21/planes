"""Survey and constraint KML reach the server, then the geo core.

HTTP to OpenTopography is mocked. The same bbox is served from the cache.
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
        ring = parse_survey_polygon(_SURVEY)
        polygons = parse_constraint_polygons(_CONSTRAINTS)
        self.assertEqual(ring[0], [37.6, 55.75])
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(polygons), 1)
        parsed = polygons[0].as_dict()
        self.assertEqual(parsed["name"], "Сектор А")
        self.assertEqual(parsed["type"], "врем_ограничение")
        self.assertEqual(parsed["altitudes_text"], "от 800 м AMSL до FL90")
        self.assertGreaterEqual(len(parsed["ring"]), 4)

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
            dem_file = result.mission_plan["dem_file"]
            self.assertTrue(str(dem_file).endswith(".tif"))
            self.assertTrue(Path(dem_file).is_file())
            self.assertEqual(len(calls), 1)
            self.assertIn("west=37.60000000", calls[0])
            self.assertIn("south=55.75000000", calls[0])
            self.assertIn("east=37.60800000", calls[0])
            self.assertIn("north=55.75400000", calls[0])
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
            self.assertEqual(len(calls), 1)
            self.assertEqual(again.mission_plan["dem_file"], dem_file)
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

    def test_missing_api_key_is_an_explicit_error(self) -> None:
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
            with self.assertRaises(ValueError) as caught:
                solve(problem, time.monotonic() + 30)
            self.assertIn("OPENTOPOGRAPHY_API_KEY", str(caught.exception))
            self.assertNotIn("flat", str(caught.exception).lower())
            import json

            response = run(json.dumps(raw).encode("utf-8"))
            self.assertEqual(response.outcome, "error")
            self.assertIsNone(response.mission_plan)
            self.assertTrue(
                any("OPENTOPOGRAPHY_API_KEY" in item for item in response.solver_report.limitations)
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

    def test_invalid_raster_is_an_explicit_error(self) -> None:
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
            with self.assertRaises(ValueError) as caught:
                solve(problem, time.monotonic() + 30)
            self.assertIn("TIFF", str(caught.exception))
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


if __name__ == "__main__":
    unittest.main()
