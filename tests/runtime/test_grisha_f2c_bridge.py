"""Bridge routing, env paths, and strip_direction ignore (no embed F2C)."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import REPO, env_vars

from planes.runtime import grisha_f2c_bridge
from planes.runtime.solver import Infeasible, Problem, Solution, TimedOut, _solve_outer, solve

_FORBIDDEN_ISO_TOKENS = (
    "grisha_f2c_bridge",
    "mvp_on_path",
    "grisha_sitecustomize",
    "sitecustomize",
)


def _assert_no_iso_plumbing(test: unittest.TestCase, lines: object) -> None:
    blob = " ".join(str(item) for item in lines)
    for token in _FORBIDDEN_ISO_TOKENS:
        test.assertNotIn(token, blob)
    test.assertNotIn("iso f2c=", blob)
    test.assertNotIn("isolated embed venv", blob)
    test.assertNotIn("fleet_catalog=", blob)
    test.assertNotIn("live path:", blob)


def _envelope(**overrides: object) -> dict:
    scenario = {
        "crs": "EPSG:4326",
        "criterion": "min_time",
        "gsd_cm_per_px": 2,
        "required_spectrum": "RGB",
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
                        "limitations": [
                            "isolated embed venv fields2cover 2.1.0 + ortools 9.9",
                            "Strip heading is solver-chosen (generateBestSwaths); a requested strip direction is ignored.",
                            "Grisha mvp sitecustomize NOT on worker path; F2C in clean subprocess",
                            "temporary flat terrain; OpenTopography was not called",
                            "fleet_catalog=/opt/planes-grisha-f2c/catalog/fleet_catalog.json",
                        ],
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
        self.assertTrue(any("generateBestSwaths" in line for line in result.limitations))
        self.assertTrue(
            any("temporary flat terrain" in line for line in result.limitations)
        )
        _assert_no_iso_plumbing(self, result.limitations)

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
        self.assertNotIn("grisha_f2c_bridge", str(caught.exception))


class PublicLimitationsTest(unittest.TestCase):
    def test_drops_iso_plumbing_keeps_product_notes(self) -> None:
        cleaned = grisha_f2c_bridge.public_limitations(
            [
                "live path: grisha_f2c_bridge → f2c_isolated_worker (generateBestSwaths)",
                "iso f2c=2.1.0 mvp_on_path=False grisha_sitecustomize=False",
                "Grisha mvp sitecustomize NOT on worker path; F2C in clean subprocess",
                "isolated embed venv fields2cover 2.1.0 + ortools 9.9",
                "fleet_catalog=/opt/planes-grisha-f2c/catalog/fleet_catalog.json",
                "temporary flat terrain; OpenTopography was not called",
                "dem_file: mono",
                "Strip heading is solver-chosen (generateBestSwaths); a requested strip direction is ignored.",
                "Wave B: recharge is a constant gap; UAV separation is a 2D horizontal heuristic",
                "Mission duration stays 2D path/speed — climb and descent time are not applied",
                "temporary flat terrain; OpenTopography was not called",
                "",
            ]
        )
        _assert_no_iso_plumbing(self, cleaned)
        self.assertEqual(
            cleaned,
            [
                "temporary flat terrain; OpenTopography was not called",
                "dem_file: mono",
                "Strip heading is solver-chosen (generateBestSwaths); a requested strip direction is ignored.",
                "Wave B: recharge is a constant gap; UAV separation is a 2D horizontal heuristic",
                "Mission duration stays 2D path/speed — climb and descent time are not applied",
            ],
        )

    def test_infeasible_worker_notes_are_also_scrubbed(self) -> None:
        class DirtyInfeasible:
            def solve(self, request, worker=None, timeout_s=0.0):
                del request, worker, timeout_s
                return {
                    "outcome": "infeasible",
                    "isolation": {"mvp_on_path": False, "grisha_sitecustomize": False},
                    "solver_report": {
                        "limitations": [
                            "iso f2c=2.1.0 mvp_on_path=False grisha_sitecustomize=False",
                            "no swaths",
                        ]
                    },
                }

        with patch.object(grisha_f2c_bridge, "_load_client", return_value=DirtyInfeasible()):
            result = grisha_f2c_bridge.solve_via_isolated_grisha_f2c(
                _problem(), time.monotonic() + 5
            )
        self.assertIsInstance(result, Infeasible)
        self.assertEqual(result.limitations, ("no swaths",))
        _assert_no_iso_plumbing(self, result.limitations)

    def test_worker_source_does_not_append_iso_plumbing(self) -> None:
        text = grisha_f2c_bridge.isolated_worker_path().read_text(encoding="utf-8")
        self.assertNotIn(
            "live path: grisha_f2c_bridge → f2c_isolated_worker (generateBestSwaths)",
            text,
        )
        self.assertNotIn("isolated embed venv fields2cover 2.1.0 + ortools 9.9", text)
        self.assertNotIn(
            "Grisha mvp sitecustomize NOT on worker path; F2C in clean subprocess",
            text,
        )
        self.assertNotIn('f"fleet_catalog={_resolve_catalog_path()}"', text)
        self.assertIn("generateBestSwaths", text)
        self.assertIn("temporary flat terrain; OpenTopography was not called", text)


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


if __name__ == "__main__":
    unittest.main()
