from __future__ import annotations

import json
import unittest
from pathlib import Path

from planes.backend.error_codes import (
    ERROR_CAMERA_NOT_IN_CATALOG,
    ERROR_CAMERA_UAV_INCOMPATIBLE,
    ERROR_MISSING_AERODROMES,
    ERROR_MODEL_NO_ENDURANCE_OR_SPEED,
    ERROR_NO_BOARDS,
    ERROR_UAV_NOT_IN_CATALOG,
    ERROR_UNKNOWN_AERODROME,
    ERROR_WORKER_EXCEPTION,
    INFEASIBLE_ENDURANCE_NO_RECHARGE,
    INFEASIBLE_NO_SWATHS,
    INFEASIBLE_TERRAIN_CLEARANCE,
    OFFLINE_ENERGY_UNCOVERED,
    TIMED_OUT_BUDGET,
    attach_classification,
    classify_result,
    public_limitations,
)
from planes.backend.models import ComputeResponse
from planes.backend.service import BackendService
from planes.backend.store import SQLiteJobStore


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ClassifyLiveSamplesTests(unittest.TestCase):
    def test_b2_recharge_off_live_response(self) -> None:
        payload = _load("B2_recharge_OFF.response.json")
        classified = classify_result(payload)
        self.assertEqual(INFEASIBLE_ENDURANCE_NO_RECHARGE, classified.error_code)
        self.assertEqual(16, classified.details["uncovered_swaths"])
        self.assertFalse(classified.details["allow_recharge"])
        self.assertIn("дозарядк", classified.message_ru or "")
        joined = " ".join(classified.public_limitations).lower()
        self.assertNotIn("sitecustomize", joined)
        self.assertNotIn("iso f2c", joined)
        self.assertNotIn("f2c_isolated_worker", joined)
        self.assertTrue(any("uncovered swaths=16" in item for item in classified.public_limitations))
        self.assertEqual(
            len(classified.public_limitations),
            len(set(classified.public_limitations)),
        )

    def test_catalog_validation_live_cases(self) -> None:
        payload = _load("catalog_validation.json")
        invalid_uav = classify_result(payload["invalid_uav"])
        self.assertEqual(ERROR_UAV_NOT_IN_CATALOG, invalid_uav.error_code)
        self.assertEqual("uav-does-not-exist-xyz", invalid_uav.details["model_id"])

        invalid_camera = classify_result(payload["invalid_camera"])
        self.assertEqual(ERROR_CAMERA_NOT_IN_CATALOG, invalid_camera.error_code)
        self.assertEqual("camera-does-not-exist-xyz", invalid_camera.details["camera_id"])

        incompatible = classify_result(payload["incompatible"])
        self.assertEqual(ERROR_CAMERA_UAV_INCOMPATIBLE, incompatible.error_code)
        self.assertEqual("geoscan-gemini", incompatible.details["model_id"])
        self.assertEqual("riebo-r4", incompatible.details["camera_id"])

        valid = classify_result(payload["valid"])
        self.assertIsNone(valid.error_code)

    def test_offline_energy_stub_is_optional(self) -> None:
        payload = _load("energy_refuse_offline.json")
        classified = classify_result(payload["B0_no_recharge"])
        self.assertEqual(OFFLINE_ENERGY_UNCOVERED, classified.error_code)
        self.assertIn("energy_refusals", classified.details)


class ClassifySchemaSignalsTests(unittest.TestCase):
    def test_no_swaths(self) -> None:
        classified = classify_result(
            {
                "contract_version": "v0",
                "outcome": "infeasible",
                "solver_report": {"method": "grisha_mvp_fields2cover_isolated", "limitations": ["no swaths"]},
                "mission_plan": None,
            }
        )
        self.assertEqual(INFEASIBLE_NO_SWATHS, classified.error_code)

    def test_terrain_clearance(self) -> None:
        classified = classify_result(
            {
                "outcome": "infeasible",
                "error": "terrain_clearance_violation",
                "solver_report": {
                    "limitations": [
                        "safety_margin_m=25: 3 clearance violation(s) detected",
                        "strict_terrain_check refused plan",
                    ]
                },
            }
        )
        self.assertEqual(INFEASIBLE_TERRAIN_CLEARANCE, classified.error_code)
        self.assertEqual(25.0, classified.details["safety_margin_m"])
        self.assertEqual(3, classified.details["terrain_clearance_errors"])

    def test_timed_out_budget(self) -> None:
        classified = classify_result(
            {
                "outcome": "timed_out",
                "error": "BudgetExhausted",
                "optimization": {"time_limit_seconds": 90},
                "solver_report": {"limitations": ["budget exhausted before route"]},
            }
        )
        self.assertEqual(TIMED_OUT_BUDGET, classified.error_code)
        self.assertEqual(90, classified.details["optimization.time_limit_seconds"])

    def test_missing_aerodromes(self) -> None:
        classified = classify_result(
            {"outcome": "error", "error": "missing fields: aerodromes"}
        )
        self.assertEqual(ERROR_MISSING_AERODROMES, classified.error_code)

    def test_unknown_aerodrome(self) -> None:
        classified = classify_result(
            {"outcome": "error", "error": "unknown aerodrome: аэродром-9"}
        )
        self.assertEqual(ERROR_UNKNOWN_AERODROME, classified.error_code)
        self.assertEqual("аэродром-9", classified.details["aerodrome_id"])

    def test_no_boards(self) -> None:
        classified = classify_result({"outcome": "error", "error": "fields2cover engine has no boards"})
        self.assertEqual(ERROR_NO_BOARDS, classified.error_code)

    def test_model_no_endurance(self) -> None:
        classified = classify_result(
            {
                "outcome": "error",
                "error": "model geoscan-201 has no positive endurance or survey/airspeed",
            }
        )
        self.assertEqual(ERROR_MODEL_NO_ENDURANCE_OR_SPEED, classified.error_code)
        self.assertEqual("geoscan-201", classified.details["model_id"])

    def test_wrap_geo_mission_aliases(self) -> None:
        self.assertEqual(
            ERROR_UAV_NOT_IN_CATALOG,
            classify_result({"outcome": "error", "error": "unknown uav model: ghost-1"}).error_code,
        )
        self.assertEqual(
            ERROR_CAMERA_NOT_IN_CATALOG,
            classify_result({"outcome": "error", "error": "unknown camera: ghost-cam"}).error_code,
        )
        self.assertEqual(
            ERROR_MODEL_NO_ENDURANCE_OR_SPEED,
            classify_result(
                {"outcome": "error", "error": "model geoscan-801 has no positive endurance or airspeed"}
            ).error_code,
        )

    def test_worker_exception_fallback(self) -> None:
        classified = classify_result(
            {
                "state": "failed",
                "job_id": "job-exc",
                "error": {"type": "RuntimeError", "message": "boom", "source": "worker"},
            }
        )
        self.assertEqual(ERROR_WORKER_EXCEPTION, classified.error_code)
        self.assertEqual("job-exc", classified.details["job_id"])
        self.assertEqual("boom", classified.details["error"])

    def test_incompatible_wins_over_camera_not_in_catalog_substring(self) -> None:
        classified = classify_result(
            {
                "outcome": "error",
                "message": "grisha_f2c_bridge: camera riebo-r4 is not compatible with model geoscan-gemini",
            }
        )
        self.assertEqual(ERROR_CAMERA_UAV_INCOMPATIBLE, classified.error_code)


class PublicLimitationsTests(unittest.TestCase):
    def test_filters_iso_and_deduplicates(self) -> None:
        cleaned = public_limitations(
            [
                "allow_recharge=false: uncovered swaths=16 (coverage needs more than one sortie under endurance)",
                "uncovered_swaths=16",
                "allow_recharge=false: uncovered swaths=16 (coverage needs more than one sortie under endurance)",
                "live path: grisha_f2c_bridge → f2c_isolated_worker (generateBestSwaths)",
                "iso f2c=2.1.0 mvp_on_path=False grisha_sitecustomize=False",
                "Traceback (most recent call last):",
            ]
        )
        self.assertEqual(
            [
                "allow_recharge=false: uncovered swaths=16 (coverage needs more than one sortie under endurance)",
                "uncovered_swaths=16",
            ],
            cleaned,
        )


class AttachClassificationTests(unittest.TestCase):
    def test_recommended_api_shape_for_live_b2(self) -> None:
        shaped = attach_classification(_load("B2_recharge_OFF.response.json"))
        self.assertEqual("infeasible", shaped["outcome"])
        self.assertEqual(INFEASIBLE_ENDURANCE_NO_RECHARGE, shaped["error_code"])
        self.assertTrue(shaped["message_ru"])
        self.assertTrue(shaped["message_en"])
        self.assertEqual(16, shaped["details"]["uncovered_swaths"])
        self.assertIn("unique_limitations", shaped["solver_report"])
        self.assertEqual(
            shaped["solver_report"]["limitations"],
            shaped["solver_report"]["unique_limitations"],
        )
        joined = " ".join(shaped["solver_report"]["limitations"]).lower()
        self.assertNotIn("sitecustomize", joined)
        self.assertNotIn("iso f2c", joined)

    def test_feasible_has_no_error_code(self) -> None:
        shaped = attach_classification(
            {
                "outcome": "feasible",
                "solver_report": {"limitations": ["iso f2c=2.1.0 mvp_on_path=False"]},
            }
        )
        self.assertNotIn("error_code", shaped)
        self.assertEqual([], shaped["solver_report"]["limitations"])


class ApiShapingLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FIXTURES.parent / f".test-error-codes-{self.id().split('.')[-1]}.sqlite3"
        self.store = SQLiteJobStore(str(self.database))
        self.service = BackendService(self.store)

    def tearDown(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database}{suffix}").unlink(missing_ok=True)

    def _complete(self, outcome: str, limitations: list[str], job_id: str = "job-shape") -> str:
        self.service.submit_job(
            scenario={"name": "shape", "crs": "EPSG:4326"},
            optimization={"objective": "min_time", "time_limit_seconds": 1},
            seed=7,
            job_id=job_id,
        )
        claimed = self.store.claim_next_queued_job()
        assert claimed is not None
        self.store.finish_with_response(
            job_id,
            ComputeResponse(
                job_id=job_id,
                outcome=outcome,  # type: ignore[arg-type]
                solver_report={"method": "test", "limitations": limitations},
            ),
        )
        return job_id

    def test_infeasible_result_is_http_payload_with_code(self) -> None:
        job_id = self._complete(
            "infeasible",
            [
                "allow_recharge=false: uncovered swaths=16 (coverage needs more than one sortie under endurance)",
                "allow_recharge=false: leftover swaths not packed into a second sortie",
                "iso f2c=2.1.0 mvp_on_path=False grisha_sitecustomize=False",
            ],
        )
        result = self.service.get_result(job_id)
        self.assertEqual("completed", result["state"])
        self.assertEqual("infeasible", result["outcome"])
        self.assertEqual(INFEASIBLE_ENDURANCE_NO_RECHARGE, result["error_code"])
        self.assertNotIn("sitecustomize", " ".join(result["solver_report"]["limitations"]))

    def test_failed_catalog_error_is_still_terminal_failed(self) -> None:
        job_id = self._complete(
            "error",
            ["grisha_f2c_bridge: uav model uav-does-not-exist-xyz not in catalog"],
            job_id="job-catalog",
        )
        result = self.service.get_result(job_id)
        self.assertEqual("failed", result["state"])
        self.assertEqual(ERROR_UAV_NOT_IN_CATALOG, result["error_code"])
        self.assertEqual("error", result["outcome"])
        self.assertEqual("uav-does-not-exist-xyz", result["details"]["model_id"])


if __name__ == "__main__":
    unittest.main()
