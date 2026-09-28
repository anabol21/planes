"""Создание PhysicsParams из каталога + конфига борта."""

from __future__ import annotations

import math

from planner.io.catalog import Catalog
from planner.models import UAVConfig
from planner.physics.base import PhysicsParams
from planner.physics.fixedwing import FixedWingPhysics
from planner.physics.rotor import RotorPhysics


def build_physics_params(
    uav: UAVConfig,
    catalog: Catalog,
    reserve_fraction: float | None = None,
    *,
    strict: bool = True,
) -> PhysicsParams:
    """Live calls are strict; old text-only fixtures must opt into strict=False."""
    if strict:
        return _strict_physics_params(uav, catalog, reserve_fraction)
    return _legacy_physics_params(uav, catalog, reserve_fraction)


_FIELDS = {
    "mass_kg": ("mass_kg", "kg"),
    "airspeed_m_s": ("v_air_mps", "m/s"),
    "survey_speed_m_s": ("v_survey_mps", "m/s"),
    "climb_m_s": ("v_climb_mps", "m/s"),
    "descent_m_s": ("v_descent_mps", "m/s"),
    "minimum_airspeed_m_s": ("v_min_mps", "m/s"),
    "flight_time_s": ("T_max_s", "s"),
    "battery_energy_wh": ("E_batt_wh", "Wh"),
    "reserve_fraction": ("reserve_fraction", "fraction"),
    "turn_time_s": ("t_turn_s", "s"),
    "max_wind_m_s": ("max_wind_m_s", "m/s"),
    "takeoff_overhead_s": ("T_catapult_s", "s"),
    "landing_overhead_s": ("T_parachute_s", "s"),
    "recharge_time_s": ("T_charge_s", "s"),
    "max_horizontal_speed_m_s": ("max_horizontal_speed_m_s", "m/s"),
}
_ZERO_ALLOWED = {"reserve_fraction", "max_wind_m_s", "takeoff_overhead_s",
                 "landing_overhead_s", "recharge_time_s", "kv", "kw"}
_MARKS = {"passport", "calculation", "estimate", "synthetic"}


def _number(block: dict, field: str, unit: str, model: str) -> float:
    entry = block.get(field)
    label = f"aircraft {model} physics.{field}"
    if not isinstance(entry, dict):
        raise ValueError(f"{label}: missing marked numeric value")
    value = entry.get("value")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0
            or (value == 0 and field not in _ZERO_ALLOWED)):
        raise ValueError(f"{label}: invalid finite physical value")
    if entry.get("unit") != unit or not isinstance(entry.get("mark"), str) or entry["mark"] not in _MARKS:
        raise ValueError(f"{label}: invalid unit or provenance mark")
    for key in ("source", "note"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise ValueError(f"{label}: missing {key}")
    return float(value)


def _strict_physics_params(uav: UAVConfig, catalog: Catalog,
                           reserve_fraction: float | None) -> PhysicsParams:
    try:
        aircraft = catalog.get_aircraft(uav.model)
    except KeyError as exc:
        raise ValueError(f"aircraft {uav.model}: missing catalog configuration") from exc
    p = aircraft.get("physics")
    if not isinstance(p, dict) or type(p.get("schema_version")) is not int or p["schema_version"] != 1:
        raise ValueError(f"aircraft {uav.model}: missing normalized physics v1")
    fw = uav.model == "geoscan201"
    if uav.model not in ("gemini", "geoscan801", "geoscan201"):
        raise ValueError(f"Unknown model: {uav.model}")
    expected = ("constant", "catapult", "parachute") if fw else ("rotor_cubic", "vertical", "vertical")
    if tuple(p.get(k) for k in ("power_model", "takeoff_mode", "landing_mode")) != expected:
        raise ValueError(f"aircraft {uav.model}: inconsistent power/takeoff/landing configuration")
    semantics = {
        "gemini": "aircraft_with_battery_and_propellers",
        "geoscan201": "MTOW_including_payload",
        "geoscan801": "complete_aircraft_mass_including_integrated_equipment_MVP",
    }
    if p.get("mass_semantics") != semantics[uav.model]:
        raise ValueError(f"aircraft {uav.model}: missing/invalid mass semantics")
    battery_id = p.get("battery_id")
    if not isinstance(battery_id, str) or not battery_id:
        raise ValueError(f"aircraft {uav.model}: missing battery_id")
    if uav.battery_id is not None and uav.battery_id != battery_id:
        raise ValueError(f"aircraft {uav.model}: unsupported battery configuration {uav.battery_id}")
    try:
        battery = catalog.get_battery(battery_id)
    except KeyError as exc:
        raise ValueError(f"aircraft {uav.model}: missing battery {battery_id}") from exc
    if (uav.model not in battery.get("for", []) or
            battery_id not in aircraft.get("related", {}).get("batteries", [])):
        raise ValueError(f"aircraft {uav.model}: incompatible battery {battery_id}")
    values = {param: _number(p, field, unit, uav.model)
              for field, (param, unit) in _FIELDS.items()}
    if values["reserve_fraction"] >= 1:
        raise ValueError(f"aircraft {uav.model}: reserve_fraction must be in [0,1)")
    if reserve_fraction is not None and reserve_fraction != values["reserve_fraction"]:
        raise ValueError(f"aircraft {uav.model}: reserve override conflicts with catalog policy")
    if not (values["v_min_mps"] <= values["v_air_mps"] <= values["max_horizontal_speed_m_s"]
            and values["v_min_mps"] <= values["v_survey_mps"] <= values["max_horizontal_speed_m_s"]):
        raise ValueError(f"aircraft {uav.model}: inconsistent working/min/max speeds")
    if fw:
        values["P_const_w"] = _number(p, "constant_power_w", "W", uav.model)
        values["v_stall_mps"] = _number(p, "stall_speed_m_s", "m/s", uav.model)
        if values["v_stall_mps"] != values["v_min_mps"]:
            raise ValueError(f"aircraft {uav.model}: inconsistent stall/minimum speed")
        # Unused rotor coefficients are explicitly zero, not cross-model defaults.
        values.update(k_h=0.0, k_v=0.0, k_w=0.0)
    else:
        for field, param, unit in (("kh", "k_h", "W/kg"), ("kv", "k_v", "W/(m/s)^3"),
                                   ("kw", "k_w", "W/(kg*(m/s)^2)")):
            values[param] = _number(p, field, unit, uav.model)
        values.update(P_const_w=0.0, v_stall_mps=0.0)
    # Compatibility alias only: live ascent/descent consumers use distinct rates.
    return PhysicsParams(uav_id=uav.id, model=uav.model,
                         v_vert_mps=values["v_climb_mps"], **values)


def validate_wind_capability(params: PhysicsParams, speed_mps: float) -> None:
    if isinstance(speed_mps, bool) or not isinstance(speed_mps, (int, float)) or not math.isfinite(speed_mps) or speed_mps < 0:
        raise ValueError("wind speed must be finite and nonnegative")
    if params.max_wind_m_s is None:
        raise ValueError(f"aircraft {params.model}: missing wind capability")
    if speed_mps > params.max_wind_m_s:
        raise ValueError(f"board {params.uav_id} aircraft {params.model}: wind {speed_mps:g} m/s "
                         f"exceeds max_wind_m_s {params.max_wind_m_s:g}; mission rejected")


def physics_provenance_notes(aircraft: dict) -> list[str]:
    """Validated live data only; publish non-passport assumptions without v0 changes."""
    model = aircraft["id"]
    return [f"aircraft {model} {field}={entry['value']} {entry['unit']} "
            f"({entry['mark']}): {entry['note']}"
            for field, entry in aircraft["physics"].items()
            if isinstance(entry, dict) and entry.get("mark") != "passport"]


def _legacy_physics_params(uav: UAVConfig, catalog: Catalog,
                           reserve_fraction: float | None) -> PhysicsParams:
    """Historical regex/default path, never used by current live solver."""
    aircraft = catalog.get_aircraft(uav.model)
    mvp = catalog.get_mvp_estimates(uav.model)
    battery = catalog.get_battery(uav.battery_id) if uav.battery_id else None

    specs = aircraft.get("specs", {})
    perf = specs.get("performance", {})

    mass_kg = _parse_mass(specs) or 2.0

    v_air = float(mvp.get("v_air_mps", 12.0))
    v_vert = float(mvp.get("v_vert_mps", 5.0))
    v_survey = float(mvp.get("v_survey_mps", v_air))

    # Скорости набора/сброса высоты (fallback — вертикальная)
    v_climb = float(mvp.get("v_climb_mps", v_vert))
    v_descent = float(mvp.get("v_descent_mps", v_vert))

    # Минимальная горизонтальная (управляемость)
    # Для мультиротора ~1 м/с; для fixed-wing — скорость сваливания
    v_min = float(
        mvp.get("v_min_mps", mvp.get("v_stall_mps", 1.0))
    )

    if battery:
        E_batt = _parse_energy(battery)
    else:
        E_batt = float(mvp.get("battery_energy_wh", 144.7))

    T_max_s = _parse_time_s(perf.get("max_flight_time", "40 min"))
    T_charge_s = _parse_charge_time_s(uav, catalog)

    return PhysicsParams(
        uav_id=uav.id,
        model=uav.model,
        mass_kg=mass_kg,
        v_air_mps=v_air,
        v_vert_mps=v_vert,
        v_survey_mps=v_survey,
        v_stall_mps=float(mvp.get("v_stall_mps", 0.0)),
        v_climb_mps=v_climb,
        v_descent_mps=v_descent,
        v_min_mps=v_min,
        E_batt_wh=E_batt,
        T_max_s=T_max_s,
        k_h=float(mvp.get("k_h", 90.0)),
        k_v=float(mvp.get("k_v", 0.02)),
        k_w=float(mvp.get("k_w", 0.008)),
        t_turn_s=5.0,
        reserve_fraction=0.05 if reserve_fraction is None else reserve_fraction,
        T_catapult_s=float(mvp.get("T_catapult_s", 0.0)),
        T_parachute_s=float(mvp.get("T_parachute_s", 0.0)),
        P_const_w=float(mvp.get("power_const_w", 0.0)),
        T_charge_s=T_charge_s,
    )


def build_physics_model(params: PhysicsParams) -> RotorPhysics | FixedWingPhysics:
    if params.model in ("gemini", "geoscan801"):
        return RotorPhysics(params)
    if params.model == "geoscan201":
        return FixedWingPhysics(params)
    raise ValueError(f"Unknown model: {params.model}")


# ============================================================
# Парсеры каталога
# ============================================================

def _parse_mass(specs: dict) -> float | None:
    raw = (
        specs.get("general", {}).get("weight")
        or specs.get("general", {}).get("max_takeoff_mass")
    )
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
    """
    Парсит строку времени в секунды.
    Поддерживает: '40 min', '~105 min', '2 h', '2400 s', '180 мин'.
    """
    if not raw:
        return 2400.0

    s = str(raw).strip()
    parts = s.split()
    if not parts:
        return 2400.0

    cleaned = "".join(c for c in parts[0] if c.isdigit() or c in ".-")
    try:
        val = float(cleaned) if cleaned else 0.0
    except ValueError:
        return 2400.0

    unit = parts[1].lower() if len(parts) > 1 else "min"
    unit = unit.rstrip(".,")

    if unit.startswith("min") or unit.startswith("мин"):
        return val * 60.0
    if unit.startswith("h") or unit.startswith("ч"):
        return val * 3600.0
    if unit.startswith("s") or unit.startswith("с"):
        return val
    return val * 60.0


def _parse_charge_time_s(uav: UAVConfig, catalog: Catalog) -> float:
    try:
        aircraft = catalog.get_aircraft(uav.model)
    except KeyError:
        return 105.0 * 60.0 if uav.model == "gemini" else 0.0

    chargers = aircraft.get("related", {}).get("chargers", [])
    for cid in chargers:
        try:
            charger = catalog._data["chargers"][cid]
        except (KeyError, AttributeError):
            continue
        ct = (
            charger.get("specs", {})
            .get("power", {})
            .get("charging_time")
        )
        if ct:
            return _parse_time_s(ct)

    if uav.model == "gemini":
        return 105.0 * 60.0
    return 0.0
