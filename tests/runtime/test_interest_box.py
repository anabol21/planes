"""Interest rectangle clips constraints before COP30. No network."""

from __future__ import annotations

import time
import unittest

from pathlib import Path
from importlib.util import find_spec

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
from planes.runtime.solver import Problem


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


class InterestBoxTest(unittest.TestCase):
    @unittest.skipUnless(find_spec("shapely"), "shapely required for polygon intersection")
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

    def test_live_bridge_receives_the_rectangle(self) -> None:
        from unittest.mock import patch
        from planes.runtime.grisha_f2c_bridge import solve_via_isolated_grisha_f2c

        calls = []
        captured = {}

        def acquire(area, **kwargs):
            calls.append((area, kwargs))
            return Path("COP30_controlled.tif")

        class Client:
            def solve(self, request, **kwargs):
                captured.update(request)
                return {
                    "outcome": "feasible",
                    "mission_plan": {"mission": {"mission_time_s": 1.0}},
                }

        scenario = {
            "crs": "EPSG:4326",
            "survey_kml": _SURVEY,
            "constraints_kml": _CONSTRAINTS,
            "aerodromes": [{"id": "pad", "lat": 55.740, "lon": 37.620}],
        }
        problem = Problem("interest", scenario, "min_time", 7, 30)
        with patch("planes.integration.terrain.iso_acquire.acquire_terrain_for_area", acquire), patch(
            "planes.runtime.grisha_f2c_bridge._load_client", return_value=Client()
        ):
            solve_via_isolated_grisha_f2c(problem, time.monotonic() + 30)
        area, kwargs = calls[0]
        from planes.integration.terrain.opentopography import bbox_from_geojson
        bounds = bbox_from_geojson(area, crs=kwargs["survey_crs"])
        self.assertEqual(bounds.normalized(), ("37.60000000", "55.74000000", "37.62000000", "55.76000000"))
        self.assertEqual(kwargs["padding_m"], 0.0)
        self.assertEqual(captured["scenario"]["constraints_kml"], _CONSTRAINTS)
        self.assertEqual(captured["scenario"]["dem_file"], "COP30_controlled.tif")
