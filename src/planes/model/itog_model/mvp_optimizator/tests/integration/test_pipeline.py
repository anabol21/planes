"""Интеграционный тест: полный pipeline на тестовых данных."""

from pathlib import Path

import pytest

from planner.solver.pipeline import run_mission


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "out"


def test_full_pipeline(out_dir):
    report = run_mission(FIXTURES, out_dir)
    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.n_uavs_used >= 1
    assert report.theta_best_deg in (0.0, 45.0, 90.0)
    assert (out_dir / "mission" / "report.json").exists()
    assert (out_dir / "mission" / "routes.kml").exists()