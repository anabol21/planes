"""Unit-тесты для энергии: модель мощности, E_to + E_ld, reserve.

Проверяет:
  - P = k_h·m + k_v·v³ (без ветра);
  - reserve_fraction по умолчанию = 0.15;
  - E_wh = E_air_wh + E_to + E_ld (инвариант Route);
  - recalc_all_routes сохраняет E_to + E_ld.
"""

from __future__ import annotations

import pytest

from planner.models import Point, Route
from planner.physics.base import PhysicsParams
from planner.physics.rotor import RotorPhysics
from planner.utils.route_metrics import (
    recalc_all_routes,
    recalc_route_metrics,
)


# ============================================================
# Фикстуры
# ============================================================

@pytest.fixture
def gemini_params():
    return PhysicsParams(
        uav_id="uav-1", model="gemini",
        mass_kg=2.0, v_air_mps=12.0, v_vert_mps=5.0,
        v_survey_mps=12.0, E_batt_wh=144.7, T_max_s=2400.0,
        k_h=90.0, k_v=0.02,
        reserve_fraction=0.15,
    )


# ============================================================
# Модель мощности
# ============================================================

def test_power_does_not_depend_on_wind(gemini_params):
    """P = k_h·m + k_v·v³, ветер не влияет."""
    m = RotorPhysics(gemini_params)
    P0 = m.power_w(12.0, 0.0)
    P5 = m.power_w(12.0, 5.0)
    P10 = m.power_w(12.0, 10.0)
    assert P0 == P5 == P10


def test_power_value(gemini_params):
    """P = 90·2 + 0.02·1728 = 214.56 Вт."""
    m = RotorPhysics(gemini_params)
    P = m.power_w(12.0, 7.0)
    assert P == pytest.approx(214.56, rel=0.01)


def test_no_kw_field():
    """PhysicsParams не имеет поля k_w."""
    assert "k_w" not in PhysicsParams.__dataclass_fields__


def test_default_reserve_015():
    """reserve_fraction по умолчанию 0.15."""
    p = PhysicsParams(
        uav_id="x", model="gemini",
        mass_kg=2.0, v_air_mps=12.0, v_vert_mps=5.0,
        v_survey_mps=12.0, E_batt_wh=144.7, T_max_s=2400.0,
    )
    assert p.reserve_fraction == 0.15


def test_power_model_calibration(gemini_params):
    """P ≈ 215 Вт → 40.4 мин полёта (паспорт 40 мин)."""
    m = RotorPhysics(gemini_params)
    P = m.power_w(12.0, 0.0)
    t_flight_min = gemini_params.E_batt_wh / P * 60
    assert t_flight_min == pytest.approx(40.5, abs=0.5)


# ============================================================
# E_to + E_ld
# ============================================================

def test_takeoff_energy(gemini_params):
    """E_to = k_h·m · (h/v_vert) / 3600."""
    m = RotorPhysics(gemini_params)
    # h=150, v_vert=5 → 30 сек
    # P = 90·2 = 180 Вт
    # E = 180·30/3600 = 1.5 Вт·ч
    E_to = m.takeoff_energy_wh(150.0)
    assert E_to == pytest.approx(1.5, rel=0.01)


def test_landing_energy_symmetric(gemini_params):
    """E_ld = E_to (для мультиротора)."""
    m = RotorPhysics(gemini_params)
    assert m.landing_energy_wh(150.0) == pytest.approx(
        m.takeoff_energy_wh(150.0)
    )


def test_takeoff_plus_landing_is_3wh(gemini_params):
    """E_to + E_ld = 3 Вт·ч при h=150."""
    m = RotorPhysics(gemini_params)
    E_total = m.takeoff_energy_wh(150.0) + m.landing_energy_wh(150.0)
    assert E_total == pytest.approx(3.0, rel=0.01)


# ============================================================
# Инвариант Route
# ============================================================

def test_route_invariant():
    """E_wh = E_air_wh + E_to + E_ld."""
    r = Route(
        uav_id="u1", flight_index=0, vpp_id="v1",
        T_air_s=200.0, E_air_wh=10.0,
        T_total_s=260.0, E_wh=13.0,   # E_to + E_ld = 3
    )
    assert r.E_wh - r.E_air_wh == pytest.approx(3.0)


def test_recalc_preserves_eto_eld(gemini_params):
    """recalc_all_routes сохраняет E_to + E_ld."""
    r = Route(
        uav_id="uav-1", flight_index=0, vpp_id="v1",
        T_air_s=100.0, E_air_wh=5.0,
        T_total_s=160.0, E_wh=8.0,   # delta = 3
        waypoints=[
            Point(lat=55.75, lon=37.62, alt_m=150.0),
            Point(lat=55.751, lon=37.62, alt_m=150.0),
        ],
    )
    delta_E_before = r.E_wh - r.E_air_wh
    assert delta_E_before == pytest.approx(3.0)

    recalc_all_routes(
        routes=[r],
        params_by_uav={"uav-1": gemini_params},
        wind_speed_mps=5.0,
        wind_direction_deg=90.0,
        P_nominal_by_uav={"uav-1": 214.56},
    )

    # После пересчёта инвариант сохранён
    delta_E_after = r.E_wh - r.E_air_wh
    assert delta_E_after == pytest.approx(delta_E_before, rel=0.01)


def test_recalc_without_e_air_wh():
    """Legacy Route без E_air_wh — delta_E = 0."""
    r = Route(
        uav_id="uav-1", flight_index=0, vpp_id="v1",
        T_air_s=100.0, E_air_wh=0.0,
        T_total_s=160.0, E_wh=5.0,
        waypoints=[
            Point(lat=55.75, lon=37.62, alt_m=150.0),
            Point(lat=55.751, lon=37.62, alt_m=150.0),
        ],
    )
    recalc_all_routes(
        routes=[r],
        params_by_uav={"uav-1": PhysicsParams(
            uav_id="uav-1", model="gemini",
            mass_kg=2.0, v_air_mps=12.0, v_vert_mps=5.0,
            v_survey_mps=12.0, E_batt_wh=144.7, T_max_s=2400.0,
        )},
        wind_speed_mps=5.0,
        wind_direction_deg=90.0,
        P_nominal_by_uav={"uav-1": 214.56},
    )
    # delta_E = 0 (E_air_wh не был задан)
    assert r.E_wh == pytest.approx(r.E_air_wh, rel=0.01)


# ============================================================
# Бюджет
# ============================================================

def test_budget_respects_reserve(gemini_params):
    """E_limit = E_batt·(1−reserve) − E_to − E_ld."""
    E_batt = gemini_params.E_batt_wh
    reserve = gemini_params.reserve_fraction

    m = RotorPhysics(gemini_params)
    E_to = m.takeoff_energy_wh(150.0)
    E_ld = m.landing_energy_wh(150.0)

    E_limit = E_batt * (1.0 - reserve) - E_to - E_ld
    # 144.7 · 0.85 − 1.5 − 1.5 = 123.0 − 3.0 = 120.0
    assert E_limit == pytest.approx(120.0, rel=0.01)