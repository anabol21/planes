"""Map engine outcome + free-text signals to stable UI-facing error codes.

Classification runs on the API result-shaping layer. It does not change the
optimizer, the runtime listener, or persisted SQLite snapshots.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping


INFEASIBLE_ENDURANCE_NO_RECHARGE = "INFEASIBLE_ENDURANCE_NO_RECHARGE"
INFEASIBLE_NO_SWATHS = "INFEASIBLE_NO_SWATHS"
INFEASIBLE_TERRAIN_CLEARANCE = "INFEASIBLE_TERRAIN_CLEARANCE"
TIMED_OUT_BUDGET = "TIMED_OUT_BUDGET"
ERROR_UAV_NOT_IN_CATALOG = "ERROR_UAV_NOT_IN_CATALOG"
ERROR_CAMERA_NOT_IN_CATALOG = "ERROR_CAMERA_NOT_IN_CATALOG"
ERROR_CAMERA_UAV_INCOMPATIBLE = "ERROR_CAMERA_UAV_INCOMPATIBLE"
ERROR_MISSING_AERODROMES = "ERROR_MISSING_AERODROMES"
ERROR_UNKNOWN_AERODROME = "ERROR_UNKNOWN_AERODROME"
ERROR_NO_BOARDS = "ERROR_NO_BOARDS"
ERROR_MODEL_NO_ENDURANCE_OR_SPEED = "ERROR_MODEL_NO_ENDURANCE_OR_SPEED"
ERROR_WORKER_EXCEPTION = "ERROR_WORKER_EXCEPTION"
OFFLINE_ENERGY_UNCOVERED = "OFFLINE_ENERGY_UNCOVERED"

_COPY: dict[str, tuple[str, str]] = {
    INFEASIBLE_ENDURANCE_NO_RECHARGE: (
        "При запрете дозарядки борт не успевает покрыть все галсы за один вылет. "
        "Включите дозарядку или добавьте борта / сократите зону.",
        "With recharge disabled the aircraft cannot cover all swaths in one sortie. "
        "Enable recharge, add aircraft, or shrink the survey area.",
    ),
    INFEASIBLE_NO_SWATHS: (
        "По зонам съёмки не получилось сгенерировать маршрутные галсы. "
        "Проверьте полигоны съёмки и запретные зоны — возможно, зона слишком мала "
        "или полностью перекрыта ограничениями.",
        "No survey swaths could be generated. Check the survey polygons and "
        "restricted zones; the area may be too small or fully blocked.",
    ),
    INFEASIBLE_TERRAIN_CLEARANCE: (
        "При строгой проверке рельефа найдены нарушения запаса высоты над землёй. "
        "Ослабьте safety_margin, поднимите AGL или отключите strict_terrain_check для демо.",
        "A strict terrain check found ground-clearance violations. Reduce the safety "
        "margin, raise AGL, or disable strict_terrain_check for the demo.",
    ),
    TIMED_OUT_BUDGET: (
        "Оптимизатор не успел построить план за отведённый лимит. "
        "Упростите сценарий или увеличьте time_limit_seconds.",
        "The optimizer did not finish a plan within the time budget. "
        "Simplify the scenario or increase time_limit_seconds.",
    ),
    ERROR_UAV_NOT_IN_CATALOG: (
        "Выбранная модель БВС нет в каталоге флота. Выберите модель из списка каталога.",
        "The selected UAV model is not in the fleet catalog. Choose a catalog model.",
    ),
    ERROR_CAMERA_NOT_IN_CATALOG: (
        "Выбранная камера отсутствует в каталоге. Выберите камеру из списка.",
        "The selected camera is not in the catalog. Choose a listed camera.",
    ),
    ERROR_CAMERA_UAV_INCOMPATIBLE: (
        "Эта камера не совместима с выбранной моделью БВС по каталогу. Выберите другую пару.",
        "This camera is not compatible with the selected UAV model. Choose another pair.",
    ),
    ERROR_MISSING_AERODROMES: (
        "В сценарии нет ни одной ВПП. Добавьте хотя бы один аэродром с координатами.",
        "The scenario has no aerodromes. Add at least one aerodrome with coordinates.",
    ),
    ERROR_UNKNOWN_AERODROME: (
        "У борта указан аэродром, которого нет в списке ВПП сценария.",
        "A board references an aerodrome that is not in the scenario list.",
    ),
    ERROR_NO_BOARDS: (
        "Добавьте хотя бы один борт (модель + камера + аэродром).",
        "Add at least one board (model + camera + aerodrome).",
    ),
    ERROR_MODEL_NO_ENDURANCE_OR_SPEED: (
        "В каталоге у выбранной модели не заданы корректные survey/airspeed или время полёта. "
        "Проверьте карточку модели.",
        "The selected model has no valid survey/airspeed or endurance in the catalog.",
    ),
    ERROR_WORKER_EXCEPTION: (
        "Внутренняя ошибка ядра планирования. Сохраните job_id и текст ошибки для команды.",
        "An internal planning error occurred. Keep the job_id and error text for the team.",
    ),
    OFFLINE_ENERGY_UNCOVERED: (
        "При текущем запасе энергии часть зон остаётся непокрытой. "
        "Разрешите возврат на дозарядку или увеличьте энергобюджет / число бортов.",
        "The current energy budget leaves some areas uncovered. Allow recharge or "
        "increase the energy budget / fleet size.",
    ),
}

_UAV_NOT_IN_CATALOG_LIVE = re.compile(
    r"uav model\s+(\S+)\s+not in catalog",
    re.IGNORECASE,
)
_UNKNOWN_UAV = re.compile(r"unknown uav model:\s+(\S+)", re.IGNORECASE)
_CAMERA_NOT_IN_CATALOG = re.compile(
    r"camera\s+(\S+)\s+not in catalog",
    re.IGNORECASE,
)
_UNKNOWN_CAMERA = re.compile(r"unknown camera:\s+(\S+)", re.IGNORECASE)
_INCOMPATIBLE = re.compile(
    r"camera\s+(\S+)\s+is not compatible with model\s+(\S+)",
    re.IGNORECASE,
)
_UNKNOWN_AERODROME = re.compile(r"unknown aerodrome:\s+(\S+)", re.IGNORECASE)
_MODEL_NO_ENDURANCE = re.compile(
    r"model\s+(\S+)\s+has no positive endurance or (?:survey/)?airspeed",
    re.IGNORECASE,
)
_UNCOVERED_SWATHS = re.compile(r"uncovered[_\s-]*swaths\s*=\s*(\d+)", re.IGNORECASE)
_ALLOW_RECHARGE = re.compile(r"allow_recharge\s*=\s*(true|false)", re.IGNORECASE)
_SAFETY_MARGIN = re.compile(r"safety_margin_m\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_CLEARANCE_COUNT = re.compile(r"(\d+)\s+clearance violation", re.IGNORECASE)
_MISSING_AERODROMES = re.compile(r"missing fields:\s*aerodromes(?:\s|$|,)", re.IGNORECASE)
_MISSING_BOARDS = re.compile(r"missing fields:\s*boards(?:\s|$|,)", re.IGNORECASE)
_NO_BOARDS = re.compile(r"\bno boards\b", re.IGNORECASE)
_NO_SWATHS = re.compile(r"^no swaths$", re.IGNORECASE)
_LEFTOVER_SWATHS = re.compile(r"leftover swaths not packed into a second sortie", re.IGNORECASE)
_UNCOVERED_NEEDS_SORTIE = re.compile(
    r"uncovered swaths=\d+.*more than one sortie under endurance",
    re.IGNORECASE,
)
_TERRAIN_ERROR = re.compile(r"terrain_clearance_violation", re.IGNORECASE)
_STRICT_TERRAIN = re.compile(r"strict_terrain_check refused plan", re.IGNORECASE)
_CLEARANCE_VIOLATION = re.compile(r"clearance violation", re.IGNORECASE)
_BUDGET = re.compile(r"budgetexhausted|budget exhausted before route", re.IGNORECASE)
_INTERNAL_LIMITATION = (
    re.compile(r"sitecustomize", re.IGNORECASE),
    re.compile(r"traceback", re.IGNORECASE),
    re.compile(r"\biso\s+f2c\s*=", re.IGNORECASE),
    re.compile(r"mvp_on_path\s*=", re.IGNORECASE),
    re.compile(r"^live path:", re.IGNORECASE),
    re.compile(r"f2c_isolated_worker", re.IGNORECASE),
    re.compile(r"grisha_sitecustomize", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class ClassifiedOutcome:
    error_code: str | None
    message_ru: str | None
    message_en: str | None
    details: dict[str, Any]
    public_limitations: tuple[str, ...]


def unique_limitations(items: list[str]) -> list[str]:
    """Preserve first-seen order and drop exact duplicate limitation strings."""
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def is_internal_limitation(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in _INTERNAL_LIMITATION)


def public_limitations(items: list[str] | tuple[str, ...] | None) -> list[str]:
    if not items:
        return []
    cleaned = [item.strip() for item in items if isinstance(item, str) and item.strip()]
    return unique_limitations([item for item in cleaned if not is_internal_limitation(item)])


def classify_result(payload: Mapping[str, Any] | None) -> ClassifiedOutcome:
    """Classify a compute result, failed-job envelope, or live sample snippet."""
    data = dict(payload or {})
    outcome, texts, limitations = _collect_signals(data)
    blob = "\n".join(texts)
    public = tuple(public_limitations(limitations))
    code, details = _match_code(outcome, blob, texts, limitations, data)
    if code is None:
        return ClassifiedOutcome(None, None, None, {}, public)
    message_ru, message_en = _COPY[code]
    return ClassifiedOutcome(code, message_ru, message_en, details, public)


def attach_classification(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied API payload with stable UI fields attached."""
    shaped = copy.deepcopy(dict(payload))
    classified = classify_result(shaped)
    _rewrite_report(shaped.get("solver_report"), classified.public_limitations)
    error = shaped.get("error")
    if isinstance(error, dict):
        _rewrite_report(error.get("solver_report"), classified.public_limitations)
        if classified.error_code:
            error.setdefault("error_code", classified.error_code)
            error.setdefault("message_ru", classified.message_ru)
    if classified.error_code:
        shaped["error_code"] = classified.error_code
        shaped["message_ru"] = classified.message_ru
        shaped["message_en"] = classified.message_en
        shaped["details"] = classified.details
        if "outcome" not in shaped:
            if classified.error_code.startswith("INFEASIBLE_"):
                shaped["outcome"] = "infeasible"
            elif classified.error_code.startswith("TIMED_OUT_"):
                shaped["outcome"] = "timed_out"
            elif classified.error_code == OFFLINE_ENERGY_UNCOVERED:
                shaped["outcome"] = shaped.get("outcome") or "infeasible"
            else:
                shaped["outcome"] = "error"
    return shaped


def _rewrite_report(report: Any, public: tuple[str, ...]) -> None:
    if not isinstance(report, dict):
        return
    report["limitations"] = list(public)
    report["unique_limitations"] = list(public)


def _collect_signals(data: Mapping[str, Any]) -> tuple[str | None, list[str], list[str]]:
    texts: list[str] = []
    limitations: list[str] = []
    outcome = data.get("outcome") if isinstance(data.get("outcome"), str) else None
    for key in ("message", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    limitations.extend(_limitations_of(data.get("solver_report")))
    error = data.get("error")
    if isinstance(error, dict):
        if outcome is None and isinstance(error.get("outcome"), str):
            outcome = error["outcome"]
        for key in ("message", "error", "type"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
        limitations.extend(_limitations_of(error.get("solver_report")))
        nested_report_error = error.get("solver_report")
        if isinstance(nested_report_error, dict) and isinstance(
            nested_report_error.get("error"), str
        ):
            texts.append(nested_report_error["error"])
    limitations.extend(item for item in texts if item not in limitations)
    if outcome is None and isinstance(data.get("state"), str) and data["state"] == "failed":
        outcome = "error"
    if outcome is None and isinstance(data.get("state"), str) and data["state"] == "timed_out":
        outcome = "timed_out"
    return outcome, texts, limitations


def _limitations_of(report: Any) -> list[str]:
    if not isinstance(report, Mapping):
        return []
    raw = report.get("limitations")
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in raw if isinstance(item, str)]


def _match_code(
    outcome: str | None,
    blob: str,
    texts: list[str],
    limitations: list[str],
    data: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    incompatible = _INCOMPATIBLE.search(blob)
    if incompatible:
        return ERROR_CAMERA_UAV_INCOMPATIBLE, {
            "model_id": incompatible.group(2),
            "camera_id": incompatible.group(1),
        }

    camera = _CAMERA_NOT_IN_CATALOG.search(blob) or _UNKNOWN_CAMERA.search(blob)
    if camera:
        return ERROR_CAMERA_NOT_IN_CATALOG, {"camera_id": camera.group(1)}

    uav = _UAV_NOT_IN_CATALOG_LIVE.search(blob) or _UNKNOWN_UAV.search(blob)
    if uav:
        return ERROR_UAV_NOT_IN_CATALOG, {"model_id": uav.group(1)}

    if _MISSING_AERODROMES.search(blob):
        return ERROR_MISSING_AERODROMES, {"error": _first_matching(texts, _MISSING_AERODROMES)}

    aerodrome = _UNKNOWN_AERODROME.search(blob)
    if aerodrome:
        return ERROR_UNKNOWN_AERODROME, {"aerodrome_id": aerodrome.group(1)}

    if _NO_BOARDS.search(blob) or _MISSING_BOARDS.search(blob):
        return ERROR_NO_BOARDS, {"error": _first_matching(texts, _NO_BOARDS) or _first_matching(texts, _MISSING_BOARDS)}

    model = _MODEL_NO_ENDURANCE.search(blob)
    if model:
        return ERROR_MODEL_NO_ENDURANCE_OR_SPEED, {"model_id": model.group(1)}

    if _is_endurance_no_recharge(outcome, blob, limitations):
        uncovered = _UNCOVERED_SWATHS.search(blob)
        allow = _ALLOW_RECHARGE.search(blob)
        details: dict[str, Any] = {"allow_recharge": False}
        if uncovered:
            details["uncovered_swaths"] = int(uncovered.group(1))
        if allow:
            details["allow_recharge"] = allow.group(1).lower() == "true"
        return INFEASIBLE_ENDURANCE_NO_RECHARGE, details

    if any(_NO_SWATHS.match(item.strip()) for item in limitations) or _NO_SWATHS.search(blob):
        return INFEASIBLE_NO_SWATHS, {
            "solver_report.limitations": public_limitations(limitations),
        }

    if (
        _TERRAIN_ERROR.search(blob)
        or _STRICT_TERRAIN.search(blob)
        or _CLEARANCE_VIOLATION.search(blob)
    ):
        details = {"error": "terrain_clearance_violation"}
        margin = _SAFETY_MARGIN.search(blob)
        if margin:
            details["safety_margin_m"] = float(margin.group(1))
        count = _CLEARANCE_COUNT.search(blob)
        if count:
            details["terrain_clearance_errors"] = int(count.group(1))
        return INFEASIBLE_TERRAIN_CLEARANCE, details

    if outcome == "timed_out" or _BUDGET.search(blob):
        details = {"error": "BudgetExhausted"}
        optimization = data.get("optimization")
        if isinstance(optimization, Mapping) and "time_limit_seconds" in optimization:
            details["optimization.time_limit_seconds"] = optimization["time_limit_seconds"]
        nested = data.get("error")
        if isinstance(nested, Mapping):
            nested_opt = nested.get("optimization")
            if isinstance(nested_opt, Mapping) and "time_limit_seconds" in nested_opt:
                details["optimization.time_limit_seconds"] = nested_opt["time_limit_seconds"]
        return TIMED_OUT_BUDGET, details

    if _is_offline_energy(data, blob):
        details = {}
        refusals = data.get("energy_refusals")
        if isinstance(refusals, list):
            details["energy_refusals"] = refusals
        uncovered = data.get("uncovered")
        if isinstance(uncovered, list):
            details["uncovered"] = uncovered
        left = data.get("E_left_Wh")
        if isinstance(left, Mapping):
            details["E_left_Wh"] = dict(left)
        return OFFLINE_ENERGY_UNCOVERED, details

    if outcome == "error" or (isinstance(data.get("state"), str) and data["state"] == "failed"):
        details = {}
        if data.get("job_id"):
            details["job_id"] = data["job_id"]
        error_text = next((item for item in texts if item not in {"RuntimeError", "ValueError", "Exception"}), None)
        if error_text and not is_internal_limitation(error_text) and "traceback" not in error_text.lower():
            details["error"] = error_text
        return ERROR_WORKER_EXCEPTION, details

    return None, {}


def _is_endurance_no_recharge(outcome: str | None, blob: str, limitations: list[str]) -> bool:
    if outcome not in {None, "infeasible"}:
        return False
    recharge_off = any(
        _ALLOW_RECHARGE.search(item) and _ALLOW_RECHARGE.search(item).group(1).lower() == "false"
        for item in (*limitations, blob)
        if _ALLOW_RECHARGE.search(item)
    )
    uncovered = bool(_UNCOVERED_SWATHS.search(blob) or _UNCOVERED_NEEDS_SORTIE.search(blob))
    leftover = bool(_LEFTOVER_SWATHS.search(blob))
    return recharge_off and (uncovered or leftover)


def _is_offline_energy(data: Mapping[str, Any], blob: str) -> bool:
    if isinstance(data.get("energy_refusals"), list) and data["energy_refusals"]:
        return True
    nested = data.get("B0_no_recharge")
    if isinstance(nested, Mapping) and nested.get("energy_refusals"):
        return True
    return "energy_refusals" in blob.lower()


def _first_matching(texts: list[str], pattern: re.Pattern[str]) -> str | None:
    for item in texts:
        if pattern.search(item):
            return item
    return None
