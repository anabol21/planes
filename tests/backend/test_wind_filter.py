from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from planes.backend.error_codes import INFEASIBLE_WIND_EXCEEDS_FLEET, classify_result
from planes.backend.service import BackendService
from planes.backend.store import SQLiteJobStore
from planes.backend.wind_filter import evaluate_wind_against_fleet
from planes.backend.worker import Worker


CATALOG = {
    "uav_models": [
        {"id": "geoscan-gemini", "max_wind_m_s": {"value": 10, "mark": "passport"}},
        {"id": "geoscan-201", "max_wind_m_s": {"value": 12, "mark": "passport"}},
        {"id": "no-wind-limit", "max_wind_m_s": None},
    ]
}


def _scenario(wind: float, *model_ids: str) -> dict[str, Any]:
    return {
        "crs": "EPSG:4326",
        "wind": {"speed_ms": wind, "direction_deg": 270},
        "boards": [
            {
                "id": f"board-{index}",
                "model_id": model_id,
                "camera_id": "cam",
                "aerodrome_id": "аэродром 1",
                "count": 1,
            }
            for index, model_id in enumerate(model_ids)
        ],
    }


class EvaluateWindTests(unittest.TestCase):
    def test_refuses_when_wind_exceeds_every_known_limit(self) -> None:
        refusal = evaluate_wind_against_fleet(_scenario(13, "geoscan-gemini", "geoscan-201"), CATALOG)
        self.assertIsNotNone(refusal)
        assert refusal is not None
        self.assertEqual(13.0, refusal.wind_mps)
        self.assertEqual(12.0, refusal.fleet_max_wind_mps)
        self.assertEqual("geoscan-201", refusal.limiting_model_id)

    def test_allows_wind_at_the_fleet_maximum(self) -> None:
        self.assertIsNone(
            evaluate_wind_against_fleet(_scenario(12, "geoscan-gemini", "geoscan-201"), CATALOG)
        )

    def test_mixed_fleet_uses_the_highest_known_limit(self) -> None:
        self.assertIsNone(evaluate_wind_against_fleet(_scenario(11, "geoscan-gemini", "geoscan-201"), CATALOG))
        refusal = evaluate_wind_against_fleet(_scenario(11, "geoscan-gemini"), CATALOG)
        self.assertIsNotNone(refusal)
        assert refusal is not None
        self.assertEqual("geoscan-gemini", refusal.limiting_model_id)
        self.assertEqual(10.0, refusal.fleet_max_wind_mps)

    def test_unknown_limit_does_not_raise_the_fleet_ceiling(self) -> None:
        refusal = evaluate_wind_against_fleet(
            _scenario(11, "geoscan-gemini", "no-wind-limit"), CATALOG
        )
        self.assertIsNotNone(refusal)
        assert refusal is not None
        self.assertEqual(("no-wind-limit",), refusal.unknown_model_ids)
        self.assertEqual(10.0, refusal.fleet_max_wind_mps)

    def test_skips_when_no_selected_model_has_a_known_limit(self) -> None:
        self.assertIsNone(evaluate_wind_against_fleet(_scenario(40, "no-wind-limit"), CATALOG))
        self.assertIsNone(evaluate_wind_against_fleet(_scenario(40, "missing-from-catalog"), CATALOG))

    def test_skips_without_wind_or_boards(self) -> None:
        self.assertIsNone(evaluate_wind_against_fleet({"boards": [{"model_id": "geoscan-gemini"}]}, CATALOG))
        self.assertIsNone(evaluate_wind_against_fleet({"wind": {"speed_ms": 40}}, CATALOG))

    def test_reads_live_fleet_catalog_passport_values(self) -> None:
        refusal = evaluate_wind_against_fleet(_scenario(10.5, "geoscan-gemini"))
        self.assertIsNotNone(refusal)
        assert refusal is not None
        self.assertEqual(10.0, refusal.fleet_max_wind_mps)
        self.assertEqual("geoscan-gemini", refusal.limiting_model_id)


class WorkerWindShortCircuitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Path(__file__).resolve().parent / f".test-wind-filter-{uuid.uuid4().hex}.sqlite3"
        self.store = SQLiteJobStore(str(self.database))
        self.service = BackendService(self.store)

    def tearDown(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database}{suffix}").unlink(missing_ok=True)

    def test_worker_returns_infeasible_without_calling_the_engine(self) -> None:
        engine = Mock()
        job_id = self.service.submit_job(
            scenario=_scenario(13, "geoscan-gemini", "geoscan-201"),
            optimization={"objective": "min_time", "time_limit_seconds": 1},
            seed=7,
            job_id="job-wind",
        )["job_id"]
        Worker(self.store, engine).run_once()
        engine.solve.assert_not_called()
        result = self.service.get_result(job_id)
        self.assertEqual("completed", result["state"])
        self.assertEqual("infeasible", result["outcome"])
        self.assertEqual(INFEASIBLE_WIND_EXCEEDS_FLEET, result["error_code"])
        self.assertEqual(13.0, result["details"]["wind_mps"])
        self.assertEqual(12.0, result["details"]["fleet_max_wind_mps"])
        self.assertEqual("geoscan-201", result["details"]["limiting_model_id"])
        self.assertIn("ветра", result["message_ru"])

    def test_existing_lifecycle_without_catalog_boards_still_reaches_engine(self) -> None:
        from planes.backend.fake_engine import FakeOptimizationEngine

        job_id = self.service.submit_job(
            scenario={"name": "legacy", "crs": "EPSG:4326"},
            optimization={"test_outcome": "feasible"},
            seed=17,
            job_id="job-legacy",
        )["job_id"]
        Worker(self.store, FakeOptimizationEngine()).run_once()
        result = self.service.get_result(job_id)
        self.assertEqual("feasible", result["outcome"])
        self.assertNotIn("error_code", result)


class ClassifyWindSignalTests(unittest.TestCase):
    def test_classifier_reads_the_stable_limitation(self) -> None:
        classified = classify_result(
            {
                "outcome": "infeasible",
                "solver_report": {
                    "method": "api_wind_filter",
                    "limitations": [
                        "wind_mps=13.0 exceeds fleet_max_wind_mps=12.0 (limiting model_id=geoscan-201)"
                    ],
                },
            }
        )
        self.assertEqual(INFEASIBLE_WIND_EXCEEDS_FLEET, classified.error_code)
        self.assertEqual(13.0, classified.details["wind_mps"])
        self.assertEqual(12.0, classified.details["fleet_max_wind_mps"])
        self.assertEqual("geoscan-201", classified.details["limiting_model_id"])


if __name__ == "__main__":
    unittest.main()
