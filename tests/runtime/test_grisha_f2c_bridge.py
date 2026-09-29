"""Bridge routing, env paths, and strip_direction ignore (no embed F2C)."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import REPO, env_vars

from planes.runtime import grisha_f2c_bridge
from planes.runtime.solver import Infeasible, Problem, Solution, TimedOut, _solve_outer, solve


def _envelope(**overrides: object) -> dict:
    scenario = {
        "crs": "EPSG:4326",
        "criterion": "min_time",
        "gsd_cm_per_px": 2,
        "required_spectrum": "RGB",
        "survey_kml": (
            "<kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>"
            "37.600,55.750 37.602,55.750 37.602,55.752 "
            "37.600,55.752 37.600,55.750"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>"
        ),
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
        "survey": {"forward_overlap": 0.6, "side_overlap": 0.5, "strip_direction_deg": 45},
        "wind": {"speed_ms": 1, "direction_deg": 90},
    }
    scenario.update(overrides)
    return scenario


def _problem(scenario: dict | None = None) -> Problem:
    return Problem(
        job_id="job_iso",
        scenario=scenario or _envelope(),
        objective="min_time",
        seed=7,
        time_limit_seconds=30,
    )


class IsolatedPathTest(unittest.TestCase):
    def test_env_overrides_client_and_worker(self) -> None:
        client = Path("/tmp/fake-f2c-client.py")
        worker = Path("/tmp/fake-f2c-worker.py")
        with env_vars(PLANES_F2C_CLIENT=str(client), PLANES_F2C_WORKER=str(worker)):
            self.assertEqual(grisha_f2c_bridge.isolated_client_path(), client)
            self.assertEqual(grisha_f2c_bridge.isolated_worker_path(), worker)

    def test_repo_tools_win_over_missing_grisha_root(self) -> None:
        with env_vars(PLANES_F2C_CLIENT=None, PLANES_F2C_WORKER=None, PLANES_GRISHA_ROOT="/no/such/grisha"):
            self.assertEqual(
                grisha_f2c_bridge.isolated_client_path(),
                REPO / "tools" / "f2c_iso" / "f2c_isolated_client.py",
            )
            self.assertEqual(
                grisha_f2c_bridge.isolated_worker_path(),
                REPO / "tools" / "f2c_iso" / "f2c_isolated_worker.py",
            )
            self.assertTrue(grisha_f2c_bridge.isolated_client_path().is_file())
            self.assertTrue(grisha_f2c_bridge.isolated_worker_path().is_file())

    def test_grisha_root_default_is_deploy_path(self) -> None:
        with env_vars(PLANES_GRISHA_ROOT=None):
            self.assertEqual(grisha_f2c_bridge.grisha_root(), Path("/opt/planes-grisha-f2c"))


class BridgeSolveTest(unittest.TestCase):
    def setUp(self) -> None:
        # These tests cover response mapping, not HTTP; the real E2E test
        # separately exercises unmocked acquisition and the child process.
        patcher = patch(
            "planes.integration.terrain.iso_acquire.acquire_terrain_for_area",
            return_value=Path("COP30_unit_fixture.tif"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_strips_direction_and_maps_feasible(self) -> None:
        captured: dict[str, object] = {}

        class FakeClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                captured["request"] = request
                captured["worker"] = worker
                captured["timeout_s"] = timeout_s
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

        with patch.object(grisha_f2c_bridge, "_load_client", return_value=FakeClient()):
            result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                _problem(), time.monotonic() + 20
            )
        self.assertIsInstance(result, Solution)
        assert isinstance(result, Solution)
        self.assertEqual(result.method, "grisha_mvp_fields2cover_isolated")
        self.assertEqual(result.objective_value, 12.5)
        request = captured["request"]
        assert isinstance(request, dict)
        self.assertEqual(request["contract_version"], "v0")
        self.assertNotIn("strip_direction_deg", request["scenario"]["survey"])
        self.assertEqual(request["scenario"]["survey"]["side_overlap"], 0.5)
        # Bridge must not re-append internal iso/bridge plumbing into limitations.
        joined = "\n".join(result.limitations)
        self.assertNotIn("live path:", joined)
        self.assertNotIn("iso f2c=", joined)
        self.assertNotIn("mvp_on_path", joined)

    def test_infeasible_and_timeout_map(self) -> None:
        class InfeasibleClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                return {
                    "outcome": "infeasible",
                    "solver_report": {"limitations": ["no swaths"]},
                }

        class TimeoutClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                return {"outcome": "timed_out", "solver_report": {"limitations": ["budget"]}}

        with patch.object(grisha_f2c_bridge, "_load_client", return_value=InfeasibleClient()):
            self.assertIsInstance(
                grisha_f2c_bridge.solve_via_isolated_grisha_f2c(_problem(), time.monotonic() + 5),
                Infeasible,
            )
        with patch.object(grisha_f2c_bridge, "_load_client", return_value=TimeoutClient()):
            self.assertIsInstance(
                grisha_f2c_bridge.solve_via_isolated_grisha_f2c(_problem(), time.monotonic() + 5),
                TimedOut,
            )

    def test_error_outcome_is_value_error(self) -> None:
        class ErrorClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                return {"outcome": "error", "error": "embed missing"}

        with patch.object(grisha_f2c_bridge, "_load_client", return_value=ErrorClient()):
            with self.assertRaises(ValueError) as caught:
                grisha_f2c_bridge.solve_via_isolated_grisha_f2c(_problem(), time.monotonic() + 5)
        self.assertIn("embed missing", str(caught.exception))


class SolveBackendTest(unittest.TestCase):
    def test_default_and_iso_alias_call_the_bridge(self) -> None:
        calls: list[str] = []

        def fake_bridge(problem, deadline):
            del problem, deadline
            calls.append("iso")
            return Infeasible(("fake-iso",))

        def boom_envelope(problem, deadline):
            del problem, deadline
            raise AssertionError("legacy envelope called")

        with patch(
            "planes.runtime.grisha_f2c_bridge.solve_via_isolated_grisha_f2c",
            fake_bridge,
        ), patch(
            "planes.runtime.geo_mission.solve_envelope",
            boom_envelope,
        ):
            with env_vars(PLANES_SOLVE_BACKEND=None):
                result = _solve_outer(_problem(), time.monotonic() + 5)
            with env_vars(PLANES_SOLVE_BACKEND="grisha_f2c_iso"):
                again = solve(_problem(), time.monotonic() + 5)
        self.assertEqual(calls, ["iso", "iso"])
        self.assertIsInstance(result, Infeasible)
        self.assertIsInstance(again, Infeasible)

    def test_legacy_rollback_calls_geo_mission(self) -> None:
        calls: list[str] = []

        def fake_envelope(problem, deadline):
            del problem, deadline
            calls.append("legacy")
            return TimedOut(("rollback",))

        def boom_bridge(problem, deadline):
            del problem, deadline
            raise AssertionError("iso bridge called")

        with patch(
            "planes.runtime.geo_mission.solve_envelope",
            fake_envelope,
        ), patch(
            "planes.runtime.grisha_f2c_bridge.solve_via_isolated_grisha_f2c",
            boom_bridge,
        ):
            for value in ("legacy_fields2cover", "legacy", "geo_mission"):
                with env_vars(PLANES_SOLVE_BACKEND=value):
                    result = _solve_outer(_problem(), time.monotonic() + 5)
                self.assertIsInstance(result, TimedOut)
        self.assertEqual(calls, ["legacy", "legacy", "legacy"])



class SpectrumFilterTest(unittest.TestCase):
    def test_mismatch_limitations_for_rgb_camera_vs_multispectral(self) -> None:
        notes = grisha_f2c_bridge.spectrum_mismatch_limitations(
            {
                "required_spectrum": "multispectral",
                "boards": [
                    {
                        "id": "БВС 1",
                        "model_id": "geoscan-gemini",
                        "camera_id": "geoscan-pf1b",
                        "aerodrome_id": "аэродром 1",
                        "count": 1,
                    }
                ],
            }
        )
        self.assertTrue(notes)
        self.assertEqual(notes[0], "no camera covers required spectrum")
        self.assertIn("geoscan-pf1b", notes[1])
        self.assertIn("multispectral", notes[1])

    def test_matching_rgb_is_not_refused(self) -> None:
        notes = grisha_f2c_bridge.spectrum_mismatch_limitations(
            {
                "required_spectrum": "RGB",
                "boards": [
                    {
                        "id": "БВС 1",
                        "model_id": "geoscan-gemini",
                        "camera_id": "geoscan-pf1b",
                        "aerodrome_id": "аэродром 1",
                        "count": 1,
                    }
                ],
            }
        )
        self.assertEqual(notes, ())

    def test_pollux_covers_multispectral(self) -> None:
        notes = grisha_f2c_bridge.spectrum_mismatch_limitations(
            {
                "required_spectrum": "multispectral",
                "boards": [
                    {
                        "model_id": "geoscan-gemini",
                        "camera_id": "geoscan-pollux",
                        "aerodrome_id": "аэродром 1",
                        "count": 1,
                    }
                ],
            }
        )
        self.assertEqual(notes, ())

    def test_bridge_refuses_before_client_on_mismatch(self) -> None:
        class BoomClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                raise AssertionError("client must not run on spectrum mismatch")

        scenario = _envelope(
            required_spectrum="multispectral",
            boards=[
                {
                    "id": "БВС 1",
                    "model_id": "geoscan-gemini",
                    "camera_id": "geoscan-pf1b",
                    "aerodrome_id": "аэродром 1",
                    "count": 1,
                }
            ],
        )
        with patch.object(grisha_f2c_bridge, "_load_client", return_value=BoomClient()):
            with patch(
                "planes.integration.terrain.iso_acquire.ensure_dem_for_iso_scenario",
                side_effect=AssertionError("DEM must not run on spectrum mismatch"),
            ):
                result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                    _problem(scenario), time.monotonic() + 5
                )
        self.assertIsInstance(result, Infeasible)
        assert isinstance(result, Infeasible)
        joined = "\n".join(result.limitations)
        self.assertIn("no camera covers required spectrum", joined)
        self.assertIn("geoscan-pf1b", joined)

    def test_bridge_matching_rgb_reaches_client(self) -> None:
        calls: list[str] = []

        class FakeClient:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                calls.append("client")
                return {
                    "outcome": "infeasible",
                    "solver_report": {"limitations": ["downstream"]},
                }

        with patch.object(grisha_f2c_bridge, "_load_client", return_value=FakeClient()):
            with patch(
                "planes.integration.terrain.iso_acquire.ensure_dem_for_iso_scenario",
                side_effect=lambda scenario, **kwargs: (scenario, ["dem-ok"]),
            ):
                result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                    _problem(_envelope(required_spectrum="RGB")),
                    time.monotonic() + 5,
                )
        self.assertEqual(calls, ["client"])
        self.assertIsInstance(result, Infeasible)



if __name__ == "__main__":
    unittest.main()
