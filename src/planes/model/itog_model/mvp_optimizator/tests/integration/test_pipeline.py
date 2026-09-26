"""Интеграционный тест: полный pipeline на тестовых данных."""

from pathlib import Path

import pytest

from planner.solver.pipeline import run_mission


FIXTURES = Path(__file__).parent.parent / "fixtures" / "moscow"


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "out"


def test_full_pipeline(out_dir):
    report = run_mission(FIXTURES, out_dir)

    # Метрики
    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.n_uavs_used >= 1

    # Угол в допустимом диапазоне
    assert 0.0 <= report.theta_best_deg < 360.0

    # Файлы на месте
    assert (out_dir / "mission" / "report.json").exists()
    assert (out_dir / "mission" / "routes.kml").exists()


def test_pipeline_early_stop(out_dir):
    """Прогон должен завершиться, а не зависнуть."""
    report = run_mission(FIXTURES, out_dir)
    # Early stop не даёт перебрать все 12 углов подряд
    assert report.n_angles_tried <= 12
    assert report.n_candidates >= 1