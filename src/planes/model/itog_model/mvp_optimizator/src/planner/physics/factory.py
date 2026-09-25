"""Создание PhysicsParams из каталога + конфига борта."""

from __future__ import annotations

from planner.io.catalog import Catalog
from planner.models import UAVConfig
from planner.physics.base import PhysicsParams
from planner.physics.fixedwing import FixedWingPhysics
from planner.physics.rotor import RotorPhysics


def build_physics_params(
    uav: UAVConfig,
    catalog: Catalog,
    reserve_fraction: float = 0.05,
) -> PhysicsParams:
    aircraft = catalog.get_aircraft(uav.model)
    mvp = catalog.get_mvp_estimates(uav.model)
    battery = catalog.get_battery(uav.battery_id) if uav.battery_id else None

    specs = aircraft.get("specs", {})
    perf = specs.get("performance", {})
    power = specs.get("power", {})

    # Масса — из паспорта или оценок
    mass_kg = _parse_mass(specs) or 2.0

    # Крейсерская скорость
    v_air = float(mvp.get("v_air_mps", 12.0))
    v_vert = float(mvp.get("v_vert_mps", 5.0))
    v_survey = float(mvp.get("v_survey_mps", v_air))

    # АКБ
    if battery:
        E_batt = _parse_energy(battery)
    else:
        E_batt = float(mvp.get("battery_energy_wh", 144.7))

    # Время полёта (из паспорта или оценки)
    T_max_s = _parse_time_s(perf.get("max_flight_time", "40 min"))

    return PhysicsParams(
        uav_id=uav.id,
        model=uav.model,
        mass_kg=mass_kg,
        v_air_mps=v_air,
        v_vert_mps=v_vert,
        v_survey_mps=v_survey,
        v_stall_mps=float(mvp.get("v_stall_mps", 0.0)),
        E_batt_wh=E_batt,
        T_max_s=T_max_s,
        k_h=float(mvp.get("k_h", 90.0)),
        k_v=float(mvp.get("k_v", 0.02)),
        k_w=float(mvp.get("k_w", 0.008)),
        t_turn_s=5.0,
        reserve_fraction=reserve_fraction,
        T_catapult_s=float(mvp.get("T_catapult_s", 0.0)),
        T_parachute_s=float(mvp.get("T_parachute_s", 0.0)),
        P_const_w=float(mvp.get("power_const_w", 0.0)),
    )


def build_physics_model(params: PhysicsParams) -> RotorPhysics | FixedWingPhysics:
    if params.model in ("gemini", "geoscan801"):
        return RotorPhysics(params)
    if params.model == "geoscan201":
        return FixedWingPhysics(params)
    raise ValueError(f"Unknown model: {params.model}")


def _parse_mass(specs: dict) -> float | None:
    """'2 kg (battery & propellers included)' → 2.0."""
    raw = specs.get("general", {}).get("weight") or specs.get("general", {}).get("max_takeoff_mass")
    if not raw:
        return None
    for token in str(raw).split():
        try:
            return float(token)
        except ValueError:
            continue
    return None


def _parse_energy(battery: dict) -> float:
    power = battery.get("specs", {}).get("power", {})
    e = power.get("energy") or power.get("energy_wh")
    if isinstance(e, (int, float)):
        return float(e)
    if isinstance(e, str):
        for token in e.replace("Wh", "").split():
            try:
                return float(token)
            except ValueError:
                continue
    return 144.7


def _parse_time_s(raw: str) -> float:
    """'40 min' → 2400 s."""
    if not raw:
        return 2400.0
    parts = str(raw).split()
    try:
        val = float(parts[0])
    except (ValueError, IndexError):
        return 2400.0
    unit = parts[1].lower() if len(parts) > 1 else "min"
    if unit.startswith("min"):
        return val * 60.0
    if unit.startswith("h"):
        return val * 3600.0
    return val