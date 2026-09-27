"""Создание PhysicsParams из каталога + конфига борта."""

from __future__ import annotations

import re

from planner.io.catalog import Catalog
from planner.models import UAVConfig
from planner.physics.base import PhysicsParams
from planner.physics.fixedwing import FixedWingPhysics
from planner.physics.rotor import RotorPhysics


_FIXED_WING_MODELS = {"geoscan201"}
_MULTIROTOR_MODELS = {"gemini", "geoscan801"}

# Дефолты, если в каталоге нет данных.
_DEFAULT_T_MAX_S = 2400.0
_DEFAULT_E_BATT_WH = 144.7
_DEFAULT_V_AIR_MPS = 12.0
_DEFAULT_V_VERT_MPS = 5.0
_DEFAULT_V_CLIMB_MPS = 3.0
_DEFAULT_V_DESCENT_MPS = 3.0
_DEFAULT_V_MIN_ROTOR_MPS = 1.0
_DEFAULT_V_STALL_FIXED_MPS = 15.0
_DEFAULT_CHARGE_TIME_GEMINI_S = 105.0 * 60.0


# ============================================================
# Публичное API
# ============================================================

def build_physics_params(
    uav: UAVConfig,
    catalog: Catalog,
    reserve_fraction: float = 0.05,
) -> PhysicsParams:
    aircraft = catalog.get_aircraft(uav.model)
    mvp = catalog.get_mvp_estimates(uav.model)
    battery = (
        catalog.get_battery(uav.battery_id) if uav.battery_id else None
    )

    specs = aircraft.get("specs", {})
    perf = specs.get("performance", {})

    is_fixed_wing = _is_fixed_wing(uav.model)

    # --- Масса ---
    mass_kg = _parse_mass(specs)
    if mass_kg is None or mass_kg <= 0:
        raise ValueError(
            f"Cannot determine mass for uav model {uav.model!r}: "
            f"check specs.general.weight or max_takeoff_mass in data.json"
        )

    # --- Скорости ---
    v_air = _float_or(mvp.get("v_air_mps"), _DEFAULT_V_AIR_MPS)
    v_survey = _float_or(mvp.get("v_survey_mps"), v_air)

    if is_fixed_wing:
        v_stall = _float_or(
            mvp.get("v_stall_mps"), _DEFAULT_V_STALL_FIXED_MPS
        )
        v_climb = _float_or(mvp.get("v_climb_mps"), _DEFAULT_V_CLIMB_MPS)
        v_descent = _float_or(
            mvp.get("v_descent_mps"), _DEFAULT_V_DESCENT_MPS
        )
        # Для fixed-wing вертикальная скорость висения не имеет смысла —
        # берём климб (для совместимости поля PhysicsParams).
        v_vert = v_climb
    else:
        v_stall = _float_or(mvp.get("v_stall_mps"), 0.0)
        v_vert = _float_or(mvp.get("v_vert_mps"), _DEFAULT_V_VERT_MPS)
        v_climb = _float_or(mvp.get("v_climb_mps"), v_vert)
        v_descent = _float_or(mvp.get("v_descent_mps"), v_vert)

    # Минимальная горизонтальная скорость:
    #   - фиксированное значение из mvp_estimates, если есть;
    #   - для fixed-wing — v_stall (ниже сваливание);
    #   - для мультироторов — 1.0 (управляемость).
    v_min_explicit = mvp.get("v_min_mps")
    if v_min_explicit is not None:
        v_min = float(v_min_explicit)
    elif is_fixed_wing:
        v_min = v_stall if v_stall > 0 else _DEFAULT_V_STALL_FIXED_MPS
    else:
        v_min = _DEFAULT_V_MIN_ROTOR_MPS

    # --- Батарея ---
    if battery is not None:
        E_batt = _parse_energy(battery)
    else:
        E_batt = _float_or(
            mvp.get("battery_energy_wh"), _DEFAULT_E_BATT_WH
        )

    # --- Время полёта ---
    T_max_s = _parse_time_s(
        perf.get("max_flight_time"),
        default=_DEFAULT_T_MAX_S,
    )

    # --- Время зарядки ---
    T_charge_s = _parse_charge_time_s(uav, catalog)

    return PhysicsParams(
        uav_id=uav.id,
        model=uav.model,
        mass_kg=mass_kg,
        v_air_mps=v_air,
        v_vert_mps=v_vert,
        v_survey_mps=v_survey,
        v_stall_mps=v_stall,
        v_climb_mps=v_climb,
        v_descent_mps=v_descent,
        v_min_mps=v_min,
        E_batt_wh=E_batt,
        T_max_s=T_max_s,
        k_h=_float_or(mvp.get("k_h"), 90.0),
        k_v=_float_or(mvp.get("k_v"), 0.02),
        k_w=_float_or(mvp.get("k_w"), 0.008),
        t_turn_s=5.0,
        reserve_fraction=reserve_fraction,
        T_catapult_s=_float_or(mvp.get("T_catapult_s"), 0.0),
        T_parachute_s=_float_or(mvp.get("T_parachute_s"), 0.0),
        P_const_w=_float_or(mvp.get("power_const_w"), 0.0),
        T_charge_s=T_charge_s,
    )


def build_physics_model(
    params: PhysicsParams,
) -> RotorPhysics | FixedWingPhysics:
    if params.model in _FIXED_WING_MODELS:
        return FixedWingPhysics(params)
    if params.model in _MULTIROTOR_MODELS:
        return RotorPhysics(params)
    raise ValueError(
        f"Unknown model: {params.model!r}. "
        f"Known: {sorted(_FIXED_WING_MODELS | _MULTIROTOR_MODELS)}"
    )


# ============================================================
# Хелперы
# ============================================================

def _is_fixed_wing(model: str) -> bool:
    return model in _FIXED_WING_MODELS


def _float_or(raw, default: float) -> float:
    """Возвращает float(raw) или default при None/пустой строке/ошибке."""
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


# ============================================================
# Парсеры каталога
# ============================================================

def _parse_mass(specs: dict) -> float | None:
    """'2 kg (battery & propellers included)' → 2.0.

    '8.5 kg' → 8.5. '1.5 kg' → 1.5.
    Приоритет: weight → max_takeoff_mass.
    """
    general = specs.get("general", {})
    raw = general.get("weight") or general.get("max_takeoff_mass")
    if not raw:
        return None

    nums = re.findall(r"(\d+(?:[.,]\d+)?)", str(raw))
    if not nums:
        return None

    try:
        return float(nums[0].replace(",", "."))
    except ValueError:
        return None


def _parse_energy(battery: dict) -> float:
    """Battery spec → Wh.

    Поддерживает:
      - energy_wh: 740 (число)
      - energy_wh: "740 Wh"
      - energy: "144.7 Wh" (строка)
    Приоритет: energy_wh → energy.
    """
    power = battery.get("specs", {}).get("power", {})

    raw = power.get("energy_wh")
    if raw is None:
        raw = power.get("energy")

    if raw is None:
        return _DEFAULT_E_BATT_WH

    if isinstance(raw, (int, float)):
        return float(raw)

    nums = re.findall(r"(\d+(?:[.,]\d+)?)", str(raw))
    if nums:
        try:
            return float(nums[0].replace(",", "."))
        except ValueError:
            pass

    return _DEFAULT_E_BATT_WH


_TIME_UNIT_TO_S = {
    "min": 60.0, "mins": 60.0, "минут": 60.0, "мин": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "ч": 3600.0, "час": 3600.0, "часа": 3600.0, "часов": 3600.0,
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "сек": 1.0, "секунд": 1.0, "с": 1.0,
}


def _parse_time_s(raw, default: float = _DEFAULT_T_MAX_S) -> float:
    """'40 min' → 2400. '~105 min' → 6300. '2 h' → 7200. '2400 s' → 2400.

    Устойчив к '~', '<', '>', запятым как десятичный разделитель.
    Если единица не распознана — считает минуты (по историческому формату).
    """
    if raw is None:
        return default

    s = str(raw).strip().lower().replace(",", ".")

    # Единица измерения (длинные альтернативы первыми, чтобы 'min' не
    # матчился раньше 'мин', а 'sec' раньше 'с')
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(hours|hour|mins|seconds|second|secs|min|hr|ч|час|часов|часа|"
        r"мин|минут|сек|секунд|с|h|s)",
        s,
    )
    if m:
        try:
            val = float(m.group(1))
        except ValueError:
            return default
        unit = m.group(2)
        factor = _TIME_UNIT_TO_S.get(unit)
        if factor is not None:
            return val * factor
        # Распозналась цифра, но единица не из словаря — по умолчанию минуты
        return val * 60.0

    # Есть только число — считаем минутами
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    if nums:
        try:
            return float(nums[0]) * 60.0
        except ValueError:
            pass

    return default


def _parse_charge_time_s(uav: UAVConfig, catalog: Catalog) -> float:
    """Время зарядки АКБ борта.

    Берёт первый charger из aircraft.related.chargers, у которого задано
    specs.power.charging_time. Fallback: 105 мин для Gemini, 0 для остальных.
    """
    try:
        aircraft = catalog.get_aircraft(uav.model)
    except KeyError:
        return _default_charge_time_s(uav.model)

    chargers = aircraft.get("related", {}).get("chargers", [])
    if not chargers:
        return _default_charge_time_s(uav.model)

    # TODO (пара 5): заменить на catalog.get_charger(cid) после рефакторинга io.
    data = getattr(catalog, "_data", {}) or {}
    chargers_data = data.get("chargers", {}) if isinstance(data, dict) else {}

    for cid in chargers:
        charger = chargers_data.get(cid)
        if not charger:
            continue
        ct = (
            charger.get("specs", {})
            .get("power", {})
            .get("charging_time")
        )
        if ct:
            return _parse_time_s(ct, default=_default_charge_time_s(uav.model))

    return _default_charge_time_s(uav.model)


def _default_charge_time_s(model: str) -> float:
    if model == "gemini":
        return _DEFAULT_CHARGE_TIME_GEMINI_S
    return 0.0