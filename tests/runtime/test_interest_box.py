"""Interest rectangle clips constraints before COP30. No network."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
import urllib.parse

import numpy as np

from planes.integration.kml.constraints import (
    ConstraintPoint,
    ConstraintPolygon,
    parse_constraint_points,
    parse_survey_polygon,
)
from planes.runtime.interest_box import (
    clip_constraint_points,
    clip_constraint_polygons,
    interest_rectangle,
    point_in_rectangle,
)
from planes.runtime.solver import Problem, solve


_SURVEY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>survey</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.600,55.750,0 37.610,55.750,0 37.610,55.760,0 37.600,55.760,0 37.600,55.750,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>route</name><LineString><coordinates>
40.000,40.000,0 41.000,41.000,0
</coordinates></LineString></Placemark>
</Document></kml>"""

_CONSTRAINTS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Covering</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.000,55.000,0 38.000,55.000,0 38.000,56.000,0 37.000,56.000,0 37.000,55.000,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>OutsidePoly</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
10.000,10.000,0 10.100,10.000,0 10.100,10.100,0 10.000,10.100,0 10.000,10.000,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>OutsidePoint</name><Point><coordinates>20.000,20.000,0</coordinates></Point></Placemark>
<Placemark><name>FarRoute</name><LineString><coordinates>
30.000,30.000,0 31.000,31.000,0
</coordinates></LineString></Placemark>
</Document></kml>"""


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


class InterestBoxTest(unittest.TestCase):
    def test_outside_point_dropped_and_covering_polygon_kept(self) -> None:
        rings = [polygon.ring for polygon in parse_survey_polygon(_SURVEY)]
        rect = interest_rectangle(rings, [(37.620, 55.740)])
        self.assertEqual(rect.crs, "EPSG:4326")
        self.assertEqual((rect.west, rect.south, rect.east, rect.north), (37.6, 55.74, 37.62, 55.76))
        self.assertLess(rect.east, 40.0)
        outside = ConstraintPoint(lon=20.0, lat=20.0, name="OutsidePoint")
        inside = ConstraintPoint(lon=37.61, lat=55.75, name="InsidePoint")
        self.assertEqual(
            [point.name for point in clip_constraint_points([outside, inside], rect)],
            ["InsidePoint"],
        )
        self.assertFalse(point_in_rectangle(outside.lon, outside.lat, rect))
        covering = ConstraintPolygon(
            ring=(
                (37.0, 55.0),
                (38.0, 55.0),
                (38.0, 56.0),
                (37.0, 56.0),
                (37.0, 55.0),
            ),
            name="Covering",
            type=None,
            altitudes_text=None,
        )
        absent = ConstraintPolygon(
            ring=((10.0, 10.0), (10.1, 10.0), (10.1, 10.1), (10.0, 10.1), (10.0, 10.0)),
            name="OutsidePoly",
            type=None,
            altitudes_text=None,
        )
        kept = clip_constraint_polygons([covering, absent], rect)
        self.assertEqual([polygon.name for polygon in kept], ["Covering"])
        parsed_points = parse_constraint_points(_CONSTRAINTS)
        self.assertEqual([point.name for point in parsed_points], ["OutsidePoint"])
        self.assertEqual(clip_constraint_points(parsed_points, rect), [])

    def test_fake_downloader_receives_the_rectangle(self) -> None:
        import planes.integration.terrain.opentopography as terrain
        import planes.runtime.geo_mission as geo_mission

        calls: list[str] = []
        geometries: list[object] = []

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

        original_open = terrain.urllib.request.urlopen
        original_acquire = geo_mission.acquire_terrain_for_area
        original_run = geo_mission._run_pipeline
        terrain.urllib.request.urlopen = opener

        def acquire(area, **kwargs):
            geometries.append(area)
            self.assertEqual(kwargs.get("survey_crs"), "EPSG:4326")
            self.assertNotIn("padding_m", kwargs)
            return original_acquire(area, **kwargs)

        seen: list[object] = []

        def run_pipeline(mission: object) -> None:
            seen.append(mission)
            return None

        geo_mission.acquire_terrain_for_area = acquire
        geo_mission._run_pipeline = run_pipeline
        cache = tempfile.mkdtemp(prefix="planes-interest-")
        previous_cache = os.environ.get("PLANES_TERRAIN_CACHE_DIR")
        previous_key = os.environ.get("OPENTOPOGRAPHY_API_KEY")
        os.environ["PLANES_TERRAIN_CACHE_DIR"] = cache
        os.environ["OPENTOPOGRAPHY_API_KEY"] = "test-key-not-a-secret"
        scenario = {
            "crs": "EPSG:4326",
            "criterion": "min_time",
            "gsd_cm_per_px": 2,
            "required_spectrum": "RGB",
            "survey_kml": _SURVEY,
            "constraints_kml": _CONSTRAINTS,
            "aerodromes": [{"id": "аэродром 1", "lat": 55.740, "lon": 37.620}],
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
        problem = Problem(
            job_id="job_interest_box",
            scenario=scenario,
            objective="min_time",
            seed=7,
            time_limit_seconds=30,
        )
        try:
            solve(problem, time.monotonic() + 30)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(geometries), 1)
            self.assertIn("west=37.60000000", calls[0])
            self.assertIn("south=55.74000000", calls[0])
            self.assertIn("east=37.62000000", calls[0])
            self.assertIn("north=55.76000000", calls[0])
            self.assertNotIn("10.000", calls[0])
            self.assertNotIn("20.000", calls[0])
            self.assertNotIn("30.000", calls[0])
            encoded = str(geometries[0])
            self.assertNotIn("10.0", encoded)
            self.assertNotIn("20.0", encoded)
            self.assertEqual(len(seen), 1)
            names = [obstacle.name for obstacle in seen[0].obstacles]
            self.assertIn("Covering", names)
            self.assertNotIn("OutsidePoly", names)
            self.assertNotIn("OutsidePoint", names)
        finally:
            geo_mission.acquire_terrain_for_area = original_acquire
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
