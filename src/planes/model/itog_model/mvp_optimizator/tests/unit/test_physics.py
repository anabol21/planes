"""Тесты физики: мощность, взлёт, посадка, ground speed.

Модель мощности:
    P = k_h·m + k_v·v³    (без k_w — ветер на мощность не влияет)

Калибровка для Gemini (m=2, v=12):
    P = 90·2 + 0.02·1728 = 214.56 Вт
    T_flight = 144.7 / 214.56 · 60 ≈ 40.5 мин
"""

import pytest

from planner.physics import build_physics_model, build_physics_params
from planner.physics.base import PhysicsParams
from planner.physics.rotor import RotorPhysics


@pytest.fixture
def gemini_params():
    return PhysicsParams(
        uav_id="uav-1",
        model="gemini",
        mass_kg=2.0,
        v_air_mps=12.0,
        v_vert_mps=5.0,
        v_survey_mps=12.0,
        E_batt_wh=144.7,
        T_max_s=2400.0,
        k_h=90.0,
        k_v=0.02,
        t_turn_s=5.0,
        reserve_fraction=0.15,
    )


# ============================================================
# Мощность
# ============================================================

def test_power_positive(gemini_params):
    """P > 0 и ≈ 215 Вт (калибровка под 40 мин)."""
    model = RotorPhysics(gemini_params)
    p = model.power_w(12.0, 7.0)
    assert p > 0
    # k_h·m = 180, + k_v·1728 ≈ 34.56, k_w убран
    # Итого ≈ 214.56 Вт
    assert p == pytest.approx(214.56, rel=0.02)


def test_power_does_not_depend_on_wind(gemini_params):
    """Ветер НЕ влияет на мощность (по указанию организаторов)."""
    model = RotorPhysics(gemini_params)
    P0 = model.power_w(12.0, 0.0)
    P5 = model.power_w(12.0, 5.0)
    P10 = model.power_w(12.0, 10.0)
    assert P0 == P5 == P10


def test_calibration_40_min(gemini_params):
    """Калибровка: 144.7 Вт·ч / 214.56 Вт ≈ 40.5 мин."""
    model = RotorPhysics(gemini_params)
    P = model.power_w(gemini_params.v_air_mps, 0.0)
    t_min = gemini_params.E_batt_wh / P * 60
    assert t_min == pytest.approx(40.5, abs=0.5)


# ============================================================
# Ground speed
# ============================================================

def test_ground_speed_with_headwind(gemini_params):
    """Worst-case: 12 − 7 = 5 м/с."""
    model = RotorPhysics(gemini_params)
    v = model.ground_speed_mps(12.0, 7.0)
    assert v == 5.0


def test_ground_speed_min_clamp(gemini_params):
    """Скорость не опускается ниже 1 м/с."""
    model = RotorPhysics(gemini_params)
    v = model.ground_speed_mps(12.0, 20.0)
    assert v == 1.0


# ============================================================
# Взлёт
# ============================================================

def test_takeoff_time(gemini_params):
    """T_to = h / v_vert = 150 / 5 = 30 сек."""
    model = RotorPhysics(gemini_params)
    t = model.takeoff_time_s(150.0)
    assert t == pytest.approx(30.0)


def test_takeoff_energy(gemini_params):
    """E_to = k_h·m · T_to / 3600 = 180 · 30 / 3600 = 1.5 Вт·ч."""
    model = RotorPhysics(gemini_params)
    e = model.takeoff_energy_wh(150.0)
    assert e == pytest.approx(1.5, rel=0.05)


def test_landing_symmetric(gemini_params):
    """E_ld = E_to."""
    model = RotorPhysics(gemini_params)
    assert model.landing_energy_wh(150.0) == pytest.approx(
        model.takeoff_energy_wh(150.0)
    )


# ============================================================
# Дефолты
# ============================================================

def test_no_kw_field():
    """PhysicsParams не имеет поля k_w."""
    assert "k_w" not in PhysicsParams.__dataclass_fields__


def test_default_reserve():
    """reserve_fraction по умолчанию 0.15."""
    p = PhysicsParams(
        uav_id="x", model="gemini",
        mass_kg=2.0, v_air_mps=12.0, v_vert_mps=5.0,
        v_survey_mps=12.0, E_batt_wh=144.7, T_max_s=2400.0,
    )
    assert p.reserve_fraction == 0.15