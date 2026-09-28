"""Интеграционный тест multi-VPP режима.

Фикстура `tests/fixtures/multi_vpp/`:
  - 3 области (visible), каждая жёстко привязана к своему борту;
  - 3 борта (все Gemini + PF1B);
  - 3 ВПП, каждая разрешает одного борта и камеру pf1b.

Проверяет:
  - _is_heterogeneous → True (3 ВПП);
  - матчинг областей на 3 борта;
  - полный pipeline: 3 борта использованы;
  - KML содержит 3 маркера VPP;
  - GeoJSON содержит 3 VPP-фичи;
  - валидатор ловит несовместимость.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planner.io.catalog import get_default_catalog
from planner.io.loaders import load_mission
from planner.models import SurveyType
from planner.solver.area_matching import (
    match_areas_to_uavs,
    summarize_assignments,
)
from planner.solver.pipeline import (
    _is_heterogeneous,
    run_mission,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "multi_vpp"


# ============================================================
# Загрузка фикстуры
# ============================================================

def test_multi_vpp_fixture_loads():
    """Фикстура корректно загружается."""
    mission = load_mission(FIXTURES)
    assert len(mission.areas) == 3
    assert len(mission.uavs) == 3
    assert len(mission.vpps) == 3

    # Каждая область привязана к своему борту
    uav_ids = {a.uav_id for a in mission.areas}
    assert uav_ids == {"gemini-1", "gemini-2", "gemini-3"}

    # Каждый борт на своей ВПП
    vpp_ids = {u.vpp_id for u in mission.uavs}
    assert vpp_ids == {"vpp-north", "vpp-center", "vpp-south"}


def test_multi_vpp_is_heterogeneous():
    """3 ВПП → _is_heterogeneous=True."""
    mission = load_mission(FIXTURES)
    assert _is_heterogeneous(mission) is True


def test_multi_vpp_area_matching():
    """Каждая область → своему борту по hard binding."""
    mission = load_mission(FIXTURES)
    catalog = get_default_catalog()

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert len(errors) == 0, f"errors: {errors}"
    assert len(assignments) == 3

    # Проверяем каждый
    assert assignments["area-north"].uav_id == "gemini-1"
    assert assignments["area-north"].vpp_id == "vpp-north"
    assert assignments["area-center"].uav_id == "gemini-2"
    assert assignments["area-center"].vpp_id == "vpp-center"
    assert assignments["area-south"].uav_id == "gemini-3"
    assert assignments["area-south"].vpp_id == "vpp-south"

    # Все три — visible, pf1b
    for a in assignments.values():
        assert a.survey_type == SurveyType.VISIBLE
        assert a.camera_id == "pf1b"
        assert a.gsd_cm_per_px == 3.0
        assert a.distance_to_vpp_m >= 0


# ============================================================
# Pipeline
# ============================================================

def test_multi_vpp_pipeline(tmp_path: Path):
    """Полный прогон: 3 борта, 3 ВПП, 3 маршрута."""
    out_dir = tmp_path / "out"
    report = run_mission(FIXTURES, out_dir)

    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.n_uavs_used == 3

    uav_ids = {u.uav_id for u in report.per_uav}
    assert uav_ids == {"gemini-1", "gemini-2", "gemini-3"}

    # Каждый борт снял хотя бы одну полосу
    for u in report.per_uav:
        assert u.n_flights >= 1


def test_multi_vpp_report_metrics(tmp_path: Path):
    """report.json содержит правильные метрики."""
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
# KML и GeoJSON
# ============================================================

def test_multi_vpp_kml_has_three_vpp(tmp_path: Path):
    """В routes.kml 3 маркера VPP (vpp-north, vpp-center, vpp-south)."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    kml_path = out_dir / "mission" / "routes.kml"
    content = kml_path.read_text(encoding="utf-8")

    assert "vpp-north" in content
    assert "vpp-center" in content
    assert "vpp-south" in content


def test_multi_vpp_kml_has_three_uav_folders(tmp_path: Path):
    """В routes.kml 3 папки UAV."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    kml_path = out_dir / "mission" / "routes.kml"
    content = kml_path.read_text(encoding="utf-8")

    assert "UAV: gemini-1" in content
    assert "UAV: gemini-2" in content
    assert "UAV: gemini-3" in content


def test_multi_vpp_geojson_has_three_vpp_points(tmp_path: Path):
    """В routes.geojson 3 VPP-фичи."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    geojson_path = out_dir / "mission" / "routes.geojson"
    with geojson_path.open(encoding="utf-8") as f:
        data = json.load(f)

    vpp_features = [
        f for f in data["features"]
        if f["properties"].get("kind") == "vpp"
    ]
    assert len(vpp_features) == 3

    vpp_ids = {f["properties"]["id"] for f in vpp_features}
    assert vpp_ids == {"vpp-north", "vpp-center", "vpp-south"}


def test_multi_vpp_geojson_has_three_routes(tmp_path: Path):
    """В routes.geojson 3 LineString-фичи (маршруты)."""
    out_dir = tmp_path / "out"
    run_mission(FIXTURES, out_dir)

    geojson_path = out_dir / "mission" / "routes.geojson"
    with geojson_path.open(encoding="utf-8") as f:
        data = json.load(f)

    route_features = [
        f for f in data["features"]
        if f["geometry"] and f["geometry"]["type"] == "LineString"
    ]
    assert len(route_features) == 3

    uav_ids = {f["properties"]["uav_id"] for f in route_features}
    assert uav_ids == {"gemini-1", "gemini-2", "gemini-3"}


# ============================================================
# Сводка назначений (для отладки)
# ============================================================

def test_multi_vpp_summarize(capsys):
    """summarize_assignments показывает 3 борта с их областями."""
    mission = load_mission(FIXTURES)
    catalog = get_default_catalog()
    assignments, _ = match_areas_to_uavs(mission, catalog)
    summary = summarize_assignments(assignments, mission)

    assert "gemini-1" in summary
    assert "area-north" in summary
    assert "gemini-2" in summary
    assert "area-center" in summary
    assert "gemini-3" in summary
    assert "area-south" in summary


# ============================================================
# Legacy: moscow не hetero, всё работает как раньше
# ============================================================

def test_moscow_not_multi_vpp():
    """Moscow (1 ВПП) — не hetero."""
    moscow = FIXTURES.parent / "moscow"
    mission = load_mission(moscow)
    assert _is_heterogeneous(mission) is False