"""Iso-path DEM wiring: acquire when missing, skip when set, mono fallback."""

from __future__ import annotations

import tempfile
import time
import unittest
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def env_vars(**updates):
    # Terrain tests do not need support's POSIX HTTP listener import.
    with patch.dict(os.environ):
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield

from planes.integration.terrain.iso_acquire import (
    DEFAULT_PADDING_M,
    ensure_dem_for_iso_scenario,
    existing_readable_dem_path,
    survey_geometry_from_scenario,
)
from planes.integration.terrain.opentopography import (
    TerrainAcquisitionError,
    bbox_from_geojson,
)
from planes.runtime import grisha_f2c_bridge
from planes.runtime.solver import Problem, Solution


_SURVEY_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>survey</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              37.600,55.750,0 37.608,55.750,0 37.608,55.754,0 37.600,55.754,0 37.600,55.750,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""


def _scenario(**overrides: object) -> dict:
    scenario = {
        "crs": "EPSG:4326",
        "criterion": "min_time",
        "gsd_cm_per_px": 2,
        "required_spectrum": "RGB",
        "survey_kml": _SURVEY_KML,
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
        "survey": {"forward_overlap": 0.6, "side_overlap": 0.5},
        "wind": {"speed_ms": 1, "direction_deg": 90},
    }
    scenario.update(overrides)
    return scenario


def _problem(scenario: dict | None = None) -> Problem:
    return Problem(
        job_id="job_iso_dem",
        scenario=scenario or _scenario(),
        objective="min_time",
        seed=7,
        time_limit_seconds=30,
    )


class _FakeClient:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured

    def solve(self, request, worker=None, timeout_s=0.0):
        self._captured["request"] = request
        self._captured["worker"] = worker
        self._captured["timeout_s"] = timeout_s
        return {
            "outcome": "feasible",
            "isolation": {
                "fields2cover_version": "2.1.0",
                "mvp_on_path": False,
                "grisha_sitecustomize": False,
            },
            "solver_report": {
                "method": "grisha_mvp_fields2cover_isolated",
                "limitations": ["isolated embed venv"],
            },
            "mission_plan": {
                "criterion": "min_time",
                "mission": {"mission_time_s": 12.5, "total_flight_time_s": 12.5},
                "routes": [],
            },
        }


class SurveyBboxTest(unittest.TestCase):
    def test_bbox_derived_from_survey_kml(self) -> None:
        geometry = survey_geometry_from_scenario(_scenario())
        self.assertEqual(geometry["type"], "Polygon")
        ring = geometry["coordinates"][0]
        lons = [point[0] for point in ring]
        lats = [point[1] for point in ring]
        self.assertAlmostEqual(min(lons), 37.600)
        self.assertAlmostEqual(max(lons), 37.608)
        self.assertAlmostEqual(min(lats), 55.750)
        self.assertAlmostEqual(max(lats), 55.754)
        bounds = bbox_from_geojson(geometry, crs="EPSG:4326", padding_m=0.0)
        self.assertEqual(bounds.west, 37.6)
        self.assertEqual(bounds.east, 37.608)
        self.assertEqual(bounds.south, 55.75)
        self.assertEqual(bounds.north, 55.754)

    def test_bbox_from_areas_geojson(self) -> None:
        scenario = _scenario()
        del scenario["survey_kml"]
        scenario["areas"] = [
            {
                "id": "cell-a",
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
        ]
        geometry = survey_geometry_from_scenario(scenario)
        self.assertEqual(geometry["type"], "Polygon")
        bounds = bbox_from_geojson(geometry, crs="EPSG:4326", padding_m=0.0)
        self.assertEqual((bounds.west, bounds.south, bounds.east, bounds.north), (37.6, 55.75, 37.608, 55.754))


class EnsureDemTest(unittest.TestCase):
    def test_acquire_called_when_dem_missing(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_acquire(area, *, survey_crs, padding_m=0.0, cache_dir=None, **_kwargs):
            calls.append(
                {
                    "area": area,
                    "survey_crs": survey_crs,
                    "padding_m": padding_m,
                    "cache_dir": cache_dir,
                }
            )
            return Path("/tmp/dems/COP30_fake.tif")

        with env_vars(PLANES_DEM_CACHE="/tmp/dems", PLANES_DEM_PADDING_M="200"):
            out, notes = ensure_dem_for_iso_scenario(_scenario(), acquire=fake_acquire)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["survey_crs"], "EPSG:4326")
        self.assertEqual(calls[0]["padding_m"], 200.0)
        self.assertEqual(Path(str(calls[0]["cache_dir"])), Path("/tmp/dems"))
        self.assertEqual(Path(out["dem_file"]), Path("/tmp/dems/COP30_fake.tif"))
        self.assertTrue(any("OpenTopography COP30 acquired" in line for line in notes))
        self.assertTrue(any("2D" in line for line in notes))
        geometry = calls[0]["area"]
        assert isinstance(geometry, dict)
        self.assertEqual(geometry["type"], "Polygon")

    def test_skipped_when_dem_already_readable(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as handle:
            handle.write(b"II*\x00not-a-real-tiff-but-readable")
            existing = Path(handle.name)
        try:

            def boom(*_args, **_kwargs):
                raise AssertionError("acquire must not be called when dem_file is readable")

            scenario = _scenario(dem_file=str(existing))
            out, notes = ensure_dem_for_iso_scenario(scenario, acquire=boom)
            self.assertEqual(Path(out["dem_file"]), existing.resolve())
            self.assertTrue(any("existing readable dem_file" in line for line in notes))
            self.assertTrue(any("OpenTopography was not called" in line for line in notes))
            self.assertEqual(existing_readable_dem_path(scenario), existing.resolve())
        finally:
            existing.unlink(missing_ok=True)

    def test_mono_alias_is_treated_as_missing(self) -> None:
        calls: list[object] = []

        def fake_acquire(area, **_kwargs):
            del area
            calls.append("acquire")
            return Path("/tmp/dems/from-mono-alias.tif")

        out, _notes = ensure_dem_for_iso_scenario(
            _scenario(dem_file="mono"), acquire=fake_acquire
        )
        self.assertEqual(calls, ["acquire"])
        self.assertEqual(Path(out["dem_file"]), Path("/tmp/dems/from-mono-alias.tif"))

    def test_missing_api_key_falls_back_to_mono(self) -> None:
        with tempfile.TemporaryDirectory(prefix="planes-dem-empty-") as cache:
            with env_vars(
                OPENTOPOGRAPHY_API_KEY=None,
                PLANES_DEM_CACHE=cache,
                PLANES_DEM_FAIL_CLOSED=None,
                PLANES_DEM_PADDING_M="0",
            ):
                scenario = _scenario()
                out, notes = ensure_dem_for_iso_scenario(scenario)
        self.assertNotIn("dem_file", out)
        self.assertTrue(any("OPENTOPOGRAPHY_API_KEY" in line for line in notes))
        self.assertTrue(any("dem_file: mono" in line for line in notes))
        self.assertTrue(any("temporary flat terrain" in line for line in notes))

    def test_fail_closed_raises_on_missing_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="planes-dem-closed-") as cache:
            with env_vars(
                OPENTOPOGRAPHY_API_KEY=None,
                PLANES_DEM_CACHE=cache,
                PLANES_DEM_FAIL_CLOSED="1",
                PLANES_DEM_PADDING_M="0",
            ):
                with self.assertRaises(TerrainAcquisitionError) as caught:
                    ensure_dem_for_iso_scenario(_scenario())
        self.assertIn("OPENTOPOGRAPHY_API_KEY", str(caught.exception))

    def test_default_padding_is_two_hundred_metres(self) -> None:
        captured: list[float] = []

        def fake_acquire(area, *, padding_m=0.0, **_kwargs):
            del area
            captured.append(padding_m)
            return Path("/tmp/dems/pad.tif")

        with env_vars(PLANES_DEM_PADDING_M=None):
            ensure_dem_for_iso_scenario(_scenario(), acquire=fake_acquire)
        self.assertEqual(captured, [DEFAULT_PADDING_M])


class BridgeDemHookTest(unittest.TestCase):
    def test_bridge_passes_acquired_dem_file_to_worker(self) -> None:
        captured: dict[str, object] = {}

        def fake_acquire(area, **_kwargs):
            del area
            return Path("/tmp/dems/bridge.tif")

        with patch(
            "planes.integration.terrain.iso_acquire.acquire_terrain_for_area",
            fake_acquire,
        ), patch.object(
            grisha_f2c_bridge, "_load_client", return_value=_FakeClient(captured)
        ):
            result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                _problem(), time.monotonic() + 20
            )
        self.assertIsInstance(result, Solution)
        request = captured["request"]
        assert isinstance(request, dict)
        self.assertEqual(Path(request["scenario"]["dem_file"]), Path("/tmp/dems/bridge.tif"))
        assert isinstance(result, Solution)
        self.assertTrue(any("OpenTopography COP30 acquired" in line for line in result.limitations))
        self.assertTrue(any("2D" in line for line in result.limitations))

    def test_bridge_validates_existing_dem_before_reuse(self) -> None:
        captured: dict[str, object] = {}
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as handle:
            handle.write(b"II*\x00existing")
            existing = Path(handle.name)
        try:

            def boom(*_args, **_kwargs):
                raise AssertionError("bridge must not re-download a readable dem_file")

            with patch(
                "planes.integration.terrain.iso_acquire.acquire_terrain_for_area",
                boom,
            ), patch(
                "planes.integration.terrain.iso_acquire._validate_geotiff",
            ) as validate, patch.object(
                grisha_f2c_bridge, "_load_client", return_value=_FakeClient(captured)
            ):
                result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                    _problem(_scenario(dem_file=str(existing))),
                    time.monotonic() + 20,
                )
            self.assertEqual(validate.call_count, 1)
            self.assertEqual(validate.call_args.args[0], existing)
            self.assertEqual(validate.call_args.args[1].normalized(),
                             ("37.60000000", "55.74800000", "37.60800000", "55.75400000"))
            request = captured["request"]
            assert isinstance(request, dict)
            self.assertEqual(Path(request["scenario"]["dem_file"]), existing.resolve())
            assert isinstance(result, Solution)
            self.assertTrue(
                any("existing readable dem_file" in line for line in result.limitations)
            )
        finally:
            existing.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
