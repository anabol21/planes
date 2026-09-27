"""Тесты физики: мощность, взлёт, посадка."""

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
        k_w=0.008,
        t_turn_s=5.0,
        reserve_fraction=0.05,
    )


def test_power_positive(gemini_params):
    model = RotorPhysics(gemini_params)
    p = model.power_w(12.0, 7.0)
    assert p > 0
    # k_h·m = 180, + k_v·1728 ≈ 34.5, + k_w·49·2 ≈ 0.78
    assert p == pytest.approx(215, rel=0.2)


def test_ground_speed_with_headwind(gemini_params):
    model = RotorPhysics(gemini_params)
    v = model.ground_speed_mps(12.0, 7.0)
    assert v == 5.0


def test_takeoff_time(gemini_params):
    model = RotorPhysics(gemini_params)
    t = model.takeoff_time_s(150.0)
    assert t == pytest.approx(30.0)


def test_takeoff_energy(gemini_params):
    model = RotorPhysics(gemini_params)
    e = model.takeoff_energy_wh(150.0)
    # P = 90·2 = 180 Вт, t = 30 с → 180·30/3600 = 1.5 Вт·ч
    assert e == pytest.approx(1.5, rel=0.05)