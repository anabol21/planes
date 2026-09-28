"""Unit-тесты для planner.solver.area_matching.

Проверяют:
  - camera_supports_survey_type — совместимость камеры и типа съёмки;
  - _uav_is_compatible — совместимость борта с областью (камера + ВПП);
  - match_areas_to_uavs — жёсткая привязка и авто-матчинг;
  - выбор по расстоянию к ВПП + балансировка;
  - обработка ошибок (нет совместимого борта).
"""

from __future__ import annotations

import pytest

from planner.io.catalog import get_default_catalog
from planner.models import (
    Area,
    MissionInput,
    Params,
    SurveyType,
    UAVConfig,
    VPP,
    Wind,
)
from planner.solver.area_matching import (
    AreaAssignment,
    camera_supports_survey_type,
    match_areas_to_uavs,
    summarize_assignments,
)


# ============================================================
# Фикстуры
# ============================================================

def _make_polygon(lon_c: float, lat_c: float, size: float = 0.001):
    """Маленький квадратный полигон вокруг центра."""
    h = size / 2
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon_c - h, lat_c - h],
            [lon_c + h, lat_c - h],
            [lon_c + h, lat_c + h],
            [lon_c - h, lat_c + h],
            [lon_c - h, lat_c - h],
        ]],
    }


def _make_mission(
    areas: list[Area],
    uavs: list[UAVConfig],
    vpps: list[VPP],
) -> MissionInput:
    return MissionInput(
        areas=areas,
        obstacles=[],
        vpps=vpps,
        uavs=uavs,
        params=Params(
            gsd_cm_per_px=3.0,
            wind=Wind(speed_mps=5.0, direction_deg=90.0),
        ),
    )


@pytest.fixture
def catalog():
    return get_default_catalog()


# ============================================================
# Совместимость камеры и survey_type
# ============================================================

def test_camera_supports_visible(catalog):
    """pf1b поддерживает visible."""
    assert camera_supports_survey_type(
        catalog, "pf1b", SurveyType.VISIBLE,
    )


def test_camera_does_not_support_thermal(catalog):
    """pf1b не поддерживает thermal."""
    assert not camera_supports_survey_type(
        catalog, "pf1b", SurveyType.THERMAL,
    )


def test_pollux_supports_multispectral(catalog):
    """pollux поддерживает visible и multispectral."""
    assert camera_supports_survey_type(
        catalog, "pollux", SurveyType.VISIBLE,
    )
    assert camera_supports_survey_type(
        catalog, "pollux", SurveyType.MULTISPECTRAL,
    )


def test_801_thermal_supports_thermal(catalog):
    """801-thermal поддерживает thermal."""
    assert camera_supports_survey_type(
        catalog, "801-thermal", SurveyType.THERMAL,
    )
    assert not camera_supports_survey_type(
        catalog, "801-thermal", SurveyType.VISIBLE,
    )


def test_unknown_camera_fallback(catalog):
    """Неизвестная камера — по умолчанию visible."""
    assert camera_supports_survey_type(
        catalog, "nonexistent-camera", SurveyType.VISIBLE,
    )
    assert not camera_supports_survey_type(
        catalog, "nonexistent-camera", SurveyType.THERMAL,
    )


# ============================================================
# Жёсткая привязка
# ============================================================

def test_hard_binding_valid(catalog):
    """Area.uav_id='u1', камера совместима — назначение проходит."""
    area = Area(
        id="a1", name="A1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
        uav_id="u1",
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62, uavs=["u1"], cameras=["pf1b"])

    mission = _make_mission([area], [uav], [vpp])
    assignments, errors = match_areas_to_uavs(mission, catalog)

    assert len(errors) == 0
    assert "a1" in assignments
    a = assignments["a1"]
    assert a.uav_id == "u1"
    assert a.vpp_id == "v1"
    assert a.camera_id == "pf1b"
    assert a.gsd_cm_per_px == 3.0
    assert a.survey_type == SurveyType.VISIBLE
    assert a.distance_to_vpp_m >= 0


def test_hard_binding_incompatible_camera(catalog):
    """Area.uav_id='u1', но камера не поддерживает survey_type — ошибка."""
    area = Area(
        id="a1",
        survey_type=SurveyType.THERMAL,
        polygon=_make_polygon(37.62, 55.75),
        uav_id="u1",
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62, cameras=["pf1b"])
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert "a1" not in assignments
    assert len(errors) == 1
    assert "pf1b" in errors[0]
    assert "thermal" in errors[0].lower()


def test_hard_binding_unknown_uav(catalog):
    """Area.uav_id не найден в uavs — ошибка."""
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
        uav_id="nonexistent",
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62)
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert "a1" not in assignments
    assert len(errors) == 1
    assert "nonexistent" in errors[0]


# ============================================================
# Авто-матчинг
# ============================================================

def test_auto_matching_visible(catalog):
    """Без uav_id — выбирается борт с совместимой камерой."""
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62, uavs=["u1"], cameras=["pf1b"])
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert len(errors) == 0
    assert assignments["a1"].uav_id == "u1"


def test_auto_matching_prefers_closer_vpp(catalog):
    """Из двух совместимых бортов выбирается тот, чья ВПП ближе."""
    # Область в точке (37.62, 55.75)
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
    )
    uav_far = UAVConfig(
        id="u-far", model="gemini", camera_id="pf1b",
        vpp_id="vpp-far",
    )
    uav_near = UAVConfig(
        id="u-near", model="gemini", camera_id="pf1b",
        vpp_id="vpp-near",
    )
    # ВПП в стороне (vpp-far далеко, vpp-near рядом)
    vpp_far = VPP(
        id="vpp-far", lat=55.80, lon=37.62,
        uavs=["u-far"], cameras=["pf1b"],
    )
    vpp_near = VPP(
        id="vpp-near", lat=55.7505, lon=37.6202,
        uavs=["u-near"], cameras=["pf1b"],
    )
    mission = _make_mission(
        [area], [uav_far, uav_near], [vpp_far, vpp_near],
    )

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert len(errors) == 0
    # Должен быть выбран u-near
    assert assignments["a1"].uav_id == "u-near"
    assert assignments["a1"].vpp_id == "vpp-near"


def test_auto_matching_no_compatible(catalog):
    """Область thermal, но ни один борт не поддерживает — ошибка."""
    area = Area(
        id="a1",
        survey_type=SurveyType.THERMAL,
        polygon=_make_polygon(37.62, 55.75),
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62)
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert "a1" not in assignments
    assert len(errors) == 1
    assert "thermal" in errors[0].lower()


# ============================================================
# Совместимость с ВПП
# ============================================================

def test_camera_not_allowed_on_vpp(catalog):
    """Камера не разрешена на ВПП — борт не подходит."""
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    # На ВПП разрешён только pollux, а у борта pf1b
    vpp = VPP(
        id="v1", lat=55.75, lon=37.62,
        uavs=["u1"], cameras=["pollux"],
    )
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert "a1" not in assignments
    assert len(errors) == 1


def test_uav_not_allowed_on_vpp(catalog):
    """Борт не разрешён на своей ВПП — не подходит."""
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    # ВПП разрешает только u2, а у нас u1
    vpp = VPP(
        id="v1", lat=55.75, lon=37.62,
        uavs=["u2"], cameras=["pf1b"],
    )
    mission = _make_mission([area], [uav], [vpp])

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert "a1" not in assignments
    assert len(errors) == 1


# ============================================================
# Несколько областей
# ============================================================

def test_multiple_areas_matched(catalog):
    """3 области с hard binding на 3 разных борта."""
    areas = [
        Area(
            id=f"a{i}",
            survey_type=SurveyType.VISIBLE,
            polygon=_make_polygon(37.62 + i * 0.01, 55.75),
            uav_id=f"u{i}",
        )
        for i in range(3)
    ]
    uavs = [
        UAVConfig(
            id=f"u{i}", model="gemini", camera_id="pf1b",
            vpp_id=f"v{i}",
        )
        for i in range(3)
    ]
    vpps = [
        VPP(
            id=f"v{i}", lat=55.75, lon=37.62 + i * 0.01,
            uavs=[f"u{i}"], cameras=["pf1b"],
        )
        for i in range(3)
    ]
    mission = _make_mission(areas, uavs, vpps)

    assignments, errors = match_areas_to_uavs(mission, catalog)
    assert len(errors) == 0
    assert len(assignments) == 3
    for i in range(3):
        assert assignments[f"a{i}"].uav_id == f"u{i}"
        assert assignments[f"a{i}"].vpp_id == f"v{i}"


# ============================================================
# Сводка
# ============================================================

def test_summarize_assignments(catalog):
    """Сводка содержит ID бортов и областей."""
    area = Area(
        id="a1",
        survey_type=SurveyType.VISIBLE,
        polygon=_make_polygon(37.62, 55.75),
        uav_id="u1",
    )
    uav = UAVConfig(
        id="u1", model="gemini", camera_id="pf1b",
        vpp_id="v1",
    )
    vpp = VPP(id="v1", lat=55.75, lon=37.62, uavs=["u1"], cameras=["pf1b"])
    mission = _make_mission([area], [uav], [vpp])

    assignments, _ = match_areas_to_uavs(mission, catalog)
    summary = summarize_assignments(assignments, mission)
    assert "u1" in summary
    assert "a1" in summary
    assert "1 area" in summary