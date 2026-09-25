"""Tiny KML rings become a scenario InputData can accept."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from planes.runtime.kml_rings import build_input_scenario
from planes.runtime.solver import Infeasible, Solution, TimedOut, _SCENARIO_FIELDS, solve


_GIBRID = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "planes"
    / "model"
    / "basic_model"
    / "gibrid-optimizer"
)

_SURVEY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>survey</name>
<Polygon><altitudeMode>clampToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
37.601,55.7480,0 37.609,55.7480,0 37.609,55.7525,0 37.601,55.7525,0 37.601,55.7480,0
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>"""

_RESTRICTION = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>placemark</name>
<ExtendedData>
  <Data name="Name"><value>Сектор А</value></Data>
  <Data name="Type"><value>врем_ограничение</value></Data>
  <Data name="Altitudes"><value>от 800 м AMSL до FL90</value></Data>
</ExtendedData>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
37.602,55.749,0 37.603,55.749,0 37.603,55.750,0 37.602,55.749,0
</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>"""

_OBSTACLES = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>BUILDING</name><Polygon><extrude>1</extrude>
<altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
37.602,55.749,48 37.603,55.749,48 37.603,55.750,48 37.602,55.749,48
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>COMMUNICATION_TOWER</name><Polygon><altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
37.0,55.0,80 38.0,55.0,80 38.0,56.0,80 37.0,56.0,80 37.0,55.0,80
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>FAR_BUILDING</name><Polygon><altitudeMode>relativeToGround</altitudeMode>
<outerBoundaryIs><LinearRing><coordinates>
10,10,20 10.1,10,20 10.1,10.1,20 10,10,20
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""

_NO_SURVEY_POLYGON = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>note</name>
<Point><coordinates>37.6,55.747,0</coordinates></Point>
</Placemark></Document></kml>"""

_TWO_SURVEY_POLYGONS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>North</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.748,0 37.609,55.748,0 37.609,55.7525,0 37.601,55.748,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>South</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
37.601,55.740,0 37.609,55.740,0 37.609,55.745,0 37.601,55.740,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""


def _scenario(**overrides: object) -> dict:
    values = {
        "survey_kml": _SURVEY,
        "restriction_kml": _RESTRICTION,
        "obstacle_kml_documents": [_OBSTACLES],
        "objective": "min_total_flight_time",
        "launch_lat": 55.7470,
        "launch_lon": 37.6000,
        "uav_model": "Geoscan Gemini",
        "uav_count": 2,
        "v_air_ms": 12.0,
        "battery_wh": 144.7,
        "max_flight_time_s": 2400,
        "wind_speed_ms": 5.0,
        "wind_direction_deg": 270.0,
    }
    values.update(overrides)
    return build_input_scenario(**values)


class KmlRingScenarioTest(unittest.TestCase):
    def test_one_survey_polygon_is_accepted_by_input_data(self) -> None:
        scenario = _scenario()
        self.assertEqual(scenario["criterion"], "min_flight_hours")
        self.assertEqual(scenario["takeoff"], {"lat": 55.7470, "lon": 37.6000})
        self.assertEqual(scenario["uav"]["count"], 2)
        self.assertEqual(scenario["uav"]["v_air_ms"], 12.0)
        self.assertEqual(scenario["uav"]["battery_wh"], 144.7)
        self.assertEqual(scenario["uav"]["max_flight_time_s"], 2400)
        self.assertEqual(scenario["wind"], {"speed_ms": 5.0, "direction_deg": 270.0})
        self.assertEqual(scenario["gsd_cm_per_px"], 3.0)
        self.assertEqual(scenario["uav"]["mass_kg"], 2.0)
        self.assertEqual(scenario["uav"]["v_vertical_ms"], 5.0)
        self.assertEqual(scenario["uav"]["max_wind_ms"], 10.0)
        self.assertIn("default profile", scenario["default_profile"]["note"])
        self.assertIn("not user input", scenario["default_profile"]["note"])
        self.assertEqual(
            scenario["zone_constraints"],
            [
                {
                    "ring": [[37.602, 55.749], [37.603, 55.749], [37.603, 55.75], [37.602, 55.749]],
                    "name": "Сектор А",
                    "type": "врем_ограничение",
                    "altitudes_text": "от 800 м AMSL до FL90",
                }
            ],
        )
        kinds = [item["kind"] for item in scenario["obstacles"]]
        self.assertEqual(kinds, ["BUILDING", "COMMUNICATION_TOWER"])
        self.assertEqual(scenario["obstacles"][0]["height_m"], 48.0)
        self.assertNotIn("FAR_BUILDING", kinds)
        for name in _SCENARIO_FIELDS:
            self.assertIn(name, scenario)

        root = str(_GIBRID)
        inserted = root not in sys.path
        if inserted:
            sys.path.insert(0, root)
        try:
            try:
                from optimizer.main import run
                from optimizer.models import InputData
            except ImportError:
                return
            payload = {name: scenario[name] for name in _SCENARIO_FIELDS}
            payload["solver"] = {"time_limit_s": 2}
            data = InputData(**payload)
            self.assertEqual(data.criterion, "min_flight_hours")
            self.assertEqual(len(data.area), 5)
            outcome = run(data, seed=7)
            self.assertIn(outcome.get("status"), ("optimal", "feasible", "heuristic"))
        finally:
            if inserted and root in sys.path:
                sys.path.remove(root)

        from planes.runtime.solver import Problem

        try:
            result = solve(
                Problem(
                    job_id="job_kml_rings",
                    scenario=scenario,
                    objective="min_flight_hours",
                    seed=7,
                    time_limit_seconds=2,
                ),
                time.monotonic() + 60,
            )
        except ValueError as exc:
            self.assertIn("optimizer import failed", str(exc))
            self.assertNotIn("infeasible", str(exc).lower())
            return
        self.assertIsInstance(result, (Solution, Infeasible, TimedOut))
        self.assertNotIsInstance(result, Infeasible)

    def test_missing_survey_polygon_is_error_not_infeasible(self) -> None:
        with self.assertRaises(ValueError) as caught:
            _scenario(survey_kml=_NO_SURVEY_POLYGON)
        message = str(caught.exception)
        self.assertIn("no polygon", message)
        self.assertNotIn("infeasible", message.lower())

    def test_multiple_survey_polygons_are_listed(self) -> None:
        with self.assertRaises(ValueError) as caught:
            _scenario(survey_kml=_TWO_SURVEY_POLYGONS)
        message = str(caught.exception)
        self.assertIn("North", message)
        self.assertIn("South", message)
        self.assertNotIn("infeasible", message.lower())


if __name__ == "__main__":
    unittest.main()
