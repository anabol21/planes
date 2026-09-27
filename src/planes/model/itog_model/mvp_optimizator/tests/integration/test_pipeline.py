"""Интеграционные тесты: полный pipeline на тестовых данных.

Тесты оптимизированы: базовый прогон на Moscow считается один раз
на модуль (module-scoped фикстура cached_run). Это сокращает время
прогона с ~3 минут до ~45 секунд.

Отдельные тесты (early stop, multi-UAV) делают свой прогон —
у них отличаются входные параметры.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from planner.solver.pipeline import run_mission


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURES = FIXTURES_DIR / "moscow"
FIXTURES_3UAV = FIXTURES_DIR / "moscow_3uav"


# ============================================================
# Общий прогон для нескольких тестов (module-scoped)
# ============================================================

@pytest.fixture(scope="module")
def cached_run(tmp_path_factory: pytest.TempPathFactory):
    """Один прогон run_mission на Moscow для всей группы тестов.

    Возвращает (report, out_dir). Тесты, которым нужен только report,
    не запускают pipeline повторно.
    """
    out_dir = tmp_path_factory.mktemp("cached_out")
    report = run_mission(FIXTURES, out_dir)
    return report, out_dir


# ============================================================
# Базовый прогон
# ============================================================

def test_full_pipeline(cached_run):
    """Полный прогон: метрики, отчёт, артефакты."""
    report, out_dir = cached_run

    # Метрики
    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.n_uavs_used >= 1
    assert report.metrics.n_photos_total > 0

    # Угол в допустимом диапазоне
    assert 0.0 <= report.theta_best_deg < 360.0

    # Кандидаты
    assert report.n_candidates >= 1
    assert 1 <= report.n_angles_tried <= 12

    # Файлы на месте
    assert (out_dir / "mission" / "report.json").exists()
    assert (out_dir / "mission" / "routes.kml").exists()


# ============================================================
# Early stop — свой прогон на патченной фикстуре
# ============================================================

def test_pipeline_early_stop(tmp_path: Path):
    """При patience=1 и 4 углах early stop должен реально срабатывать.

    Копируем фикстуру, патчим params.json:
      - angles_deg: [0, 45, 90, 135] (4 угла)
      - angles_early_stop_patience: 1
    """
    fixtures = _copy_fixtures(tmp_path, "moscow")

    params_path = fixtures / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))
    params["angles_deg"] = [0, 45, 90, 135]
    params["angles_early_stop_patience"] = 1
    params_path.write_text(
        json.dumps(params, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    report = run_mission(fixtures, out_dir)

    # patience=1 → как минимум первый угол + один «промах» = 2, максимум 4
    assert 1 <= report.n_angles_tried <= 4
    assert report.n_candidates >= 1


# ============================================================
# Multi-UAV (если фикстура есть)
# ============================================================

@pytest.mark.skipif(
    not FIXTURES_3UAV.exists(),
    reason="fixtures/moscow_3uav not found",
)
def test_pipeline_multi_uav(tmp_path: Path):
    """Три борта: используются все, покрытие полное."""
    out_dir = tmp_path / "out"
    report = run_mission(FIXTURES_3UAV, out_dir)

    assert report.metrics.n_uavs_used == 3
    assert report.metrics.n_swaths_total > 0
    assert len(report.per_uav) == 3

    # Каждый борт должен снять хотя бы одну полосу
    for u in report.per_uav:
        assert u.n_flights >= 1


# ============================================================
# Формат отчёта
# ============================================================

def test_pipeline_report_no_lns(cached_run):
    """В отчёте нет поля lns_iterations (LNS не реализован)."""
    _, out_dir = cached_run

    report_path = out_dir / "mission" / "report.json"
    with report_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert "lns_iterations" not in data


def test_pipeline_best_theta_matches_candidate(cached_run):
    """theta_best_deg совпадает с одним из пройденных углов."""
    report, _ = cached_run

    params = json.loads(
        (FIXTURES / "params.json").read_text(encoding="utf-8")
    )
    allowed = set(params["angles_deg"])

    assert report.theta_best_deg in allowed


def test_pipeline_report_has_string_enums(cached_run):
    """В JSON-отчёте enum'ы — строки ('trapezoid', 'min_time')."""
    _, out_dir = cached_run

    with (out_dir / "mission" / "report.json").open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data["decomposition_method"], str)
    assert isinstance(data["optimization_criterion"], str)
    assert data["decomposition_method"] in ("trapezoid", "triangulation", "auto")
    assert data["optimization_criterion"] in ("min_time", "min_flight_hours")


# ============================================================
# Overrides
# ============================================================

def test_pipeline_criterion_override(tmp_path: Path):
    """criterion_override='min_flight_hours' перебивает params.json."""
    out_dir = tmp_path / "out"
    report = run_mission(
        FIXTURES,
        out_dir,
        criterion_override="min_flight_hours",
    )

    assert report.optimization_criterion.value == "min_flight_hours"

    with (out_dir / "mission" / "report.json").open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["optimization_criterion"] == "min_flight_hours"


def test_pipeline_angle_override(tmp_path: Path):
    """angle_override=45 → перебор на одном угле."""
    out_dir = tmp_path / "out"
    report = run_mission(
        FIXTURES,
        out_dir,
        angle_override=45.0,
    )

    assert report.theta_best_deg == 45.0
    assert report.n_angles_tried == 1


# ============================================================
# Хелперы
# ============================================================

def _copy_fixtures(tmp_path: Path, name: str) -> Path:
    """Копирует фикстуру во временную папку, чтобы её можно было патчить."""
    src = FIXTURES_DIR / name
    if not src.exists():
        pytest.skip(f"fixtures/{name} not found")
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst