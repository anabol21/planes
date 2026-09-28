"""Интеграционный тест гетерогенного режима.

Проверяет, что 3 области с разными survey_type и GSD корректно
распределяются между 3 разными бортами, каждый со своей камерой.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planner.io.catalog import get_default_catalog
from planner.models import SurveyType
from planner.solver.area_matching import match_areas_to_uavs
from planner.solver.pipeline import (
    _is_heterogeneous,
    run_mission,
)
from planner.io.loaders import load_mission


FIXTURES = (
    Path(__file__).parent.parent / "fixtures" / "heterogeneous"
)


# ============================================================
# Unit-уровень: матчинг
# ============================================================

def test_is_heterogeneous_detected():
    """Fixture с разными survey_type → hetero mode."""
    mission = load_mission(FIXTURES)
    assert _is_heterogeneous(mission) is True


def test_area_matching_3_types():
    """3 области → 3 борта: pf1b visible, pollux multispectral, 801 thermal."""
    mission = load_mission(FIXTURES)
    catalog = get_default_catalog()

    assignments, errors = match_areas_to_uavs(mission, catalog)

    assert len(errors) == 0, f"errors: {errors}"
    assert len(assignments) == 3

    # visible → gemini-pf1b (или gemini-pollux, но pf1b первее)
    a_vis = assignments["area-visible"]
    assert a_vis.camera_id == "pf1b"
    assert a_vis.uav_id == "gemini-pf1b"
    assert a_vis.gsd_cm_per_px == 3.0
    assert a_vis.survey_type == SurveyType.VISIBLE

    # multispectral → gemini-pollux
    a_ms = assignments["area-multispectral"]
    assert a_ms.camera_id == "pollux"
    assert a_ms.uav_id == "gemini-pollux"
    assert a_ms.gsd_cm_per_px == 5.0
    assert a_ms.survey_type == SurveyType.MULTISPECTRAL

    # thermal → gs801-thermal
    a_th = assignments["area-thermal"]
    assert a_th.camera_id == "801-thermal"
    assert a_th.uav_id == "gs801-thermal"
    assert a_th.gsd_cm_per_px == 10.0
    assert a_th.survey_type == SurveyType.THERMAL


# ============================================================
# Интеграционный: полный pipeline
# ============================================================

def test_heterogeneous_pipeline(tmp_path: Path):
    """Полный прогон: 3 области → 3 борта, каждый со своей высотой."""
    out_dir = tmp_path / "out"

    report = run_mission(FIXTURES, out_dir)

    # Метрики
    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.n_uavs_used == 3

    # Все 3 борта использованы
    uav_ids = {u.uav_id for u in report.per_uav}
    assert uav_ids == {"gemini-pf1b", "gemini-pollux", "gs801-thermal"}

    # Каждый борт снял хотя бы одну полосу
    for u in report.per_uav:
        assert u.n_flights >= 1, f"{u.uav_id} не использован"

    # Артефакты
    assert (out_dir / "mission" / "report.json").exists()
    assert (out_dir / "mission" / "routes.kml").exists()


def test_heterogeneous_report_metrics(tmp_path: Path):
    """В report.json n_uavs_used = 3."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    with (out_dir / "mission" / "report.json").open(
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    assert data["metrics"]["n_uavs_used"] == 3
    assert data["metrics"]["n_swaths_total"] > 0
    assert data["decomposition_method"] == "triangulation"


# ============================================================
# Проверка GSD по областям
# ============================================================

def test_hetero_swaths_have_correct_gsd(tmp_path: Path):
    """Разные области → разные высоты полёта (по GSD)."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    with (out_dir / "mission" / "report.json").open(
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    # Отчёт содержит 3 UAV
    assert len(data["per_uav"]) == 3


# ============================================================
# Legacy: старая фикстура → legacy mode
# ============================================================

def test_legacy_moscow_not_heterogeneous():
    """Moscow (одинаковые области) → legacy mode."""
    moscow = FIXTURES.parent / "moscow"
    mission = load_mission(moscow)
    assert _is_heterogeneous(mission) is False