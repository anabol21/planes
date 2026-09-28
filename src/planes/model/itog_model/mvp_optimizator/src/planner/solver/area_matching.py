"""Матчинг областей съёмки к бортам.

Правила:
  1. Если Area.uav_id задан — жёсткая привязка. Проверяется, что
     камера этого борта поддерживает survey_type области.
  2. Иначе — выбирается среди СОВМЕСТИМЫХ бортов:
     - камера поддерживает survey_type области;
     - камера разрешена на ВПП борта (vpp.cameras);
     - борт разрешён на ВПП (vpp.uavs).
     Из них выбирается тот, у которого:
       score = distance(area → vpp) + BALANCE_PENALTY_M × n_assigned
     минимален.
     BALANCE_PENALTY_M — условный «штраф» за уже назначенные
     области, чтобы не грузить один борт.
  3. Если ни один борт не подходит — область пропускается
     с warning.

Это даёт гетерогенность и корректное распределение по ВПП:
каждая область идёт борту с совместимой камерой, чья ВПП
ближе и которая разрешает борт/камеру.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import shape

from planner.io.catalog import Catalog
from planner.models import (
    Area,
    MissionInput,
    Point,
    SurveyType,
    UAVConfig,
    VPP,
)
from planner.utils.logging import log_error, log_warn
from planner.utils.route_metrics import haversine_m


# Условный штраф за каждую уже назначенную на борт область (в метрах).
# Если разница расстояний > этого значения, близость ВПП важнее
# балансировки.
BALANCE_PENALTY_M = 1000.0


@dataclass
class AreaAssignment:
    """Результат матчинга: какая область какому борту назначена."""

    area_id: str
    uav_id: str
    vpp_id: str
    camera_id: str
    gsd_cm_per_px: float
    survey_type: SurveyType
    distance_to_vpp_m: float


# ============================================================
# Совместимость камеры и типа съёмки
# ============================================================

def camera_supports_survey_type(
    catalog: Catalog,
    camera_id: str,
    survey_type: SurveyType,
) -> bool:
    """True, если камера поддерживает заданный тип съёмки.

    Делегирует в Catalog.camera_supports.
    """
    return catalog.camera_supports(camera_id, survey_type)


# ============================================================
# Геометрия
# ============================================================

def _area_centroid(area: Area) -> tuple[float, float]:
    """Центроид области в градусах: (lat, lon)."""
    poly = shape(area.polygon)
    c = poly.centroid
    return float(c.y), float(c.x)


def _distance_area_to_vpp(area: Area, vpp: VPP) -> float:
    """Расстояние от центроида области до ВПП, метры."""
    lat, lon = _area_centroid(area)
    return haversine_m(
        Point(lat=lat, lon=lon),
        Point(lat=vpp.lat, lon=vpp.lon),
    )


# ============================================================
# Совместимость борта с областью (с учётом ВПП)
# ============================================================

def _uav_is_compatible(
    uav: UAVConfig,
    area: Area,
    mission: MissionInput,
    catalog: Catalog,
) -> tuple[bool, VPP | None, str]:
    """Проверяет совместимость борта с областью.

    Returns:
        (compatible, vpp, reason).
        reason — пусто, если ок; иначе причина несовместимости.
    """
    # Камера поддерживает survey_type?
    if not catalog.camera_supports(uav.camera_id, area.survey_type):
        return False, None, (
            f"камера {uav.camera_id!r} не поддерживает "
            f"survey_type={area.survey_type.value!r}"
        )

    # ВПП борта существует?
    try:
        vpp = mission.vpp_by_id(uav.vpp_id)
    except KeyError:
        return False, None, f"vpp_id={uav.vpp_id!r} не найден"

    # Камера разрешена на ВПП?
    if not vpp.has_camera(uav.camera_id):
        return False, vpp, (
            f"камера {uav.camera_id!r} не разрешена на ВПП {vpp.id!r} "
            f"(разрешены: {sorted(vpp.cameras)})"
        )

    # Борт разрешён на ВПП?
    if not vpp.has_uav(uav.id):
        return False, vpp, (
            f"борт {uav.id!r} не разрешён на ВПП {vpp.id!r} "
            f"(разрешены: {sorted(vpp.uavs)})"
        )

    return True, vpp, ""


def _find_compatible_uavs(
    mission: MissionInput,
    catalog: Catalog,
    area: Area,
) -> list[tuple[UAVConfig, VPP]]:
    """Борта, совместимые с областью, вместе с их ВПП."""
    result: list[tuple[UAVConfig, VPP]] = []
    for uav in mission.uavs:
        ok, vpp, _reason = _uav_is_compatible(uav, area, mission, catalog)
        if ok and vpp is not None:
            result.append((uav, vpp))
    return result


# ============================================================
# Основной матчинг
# ============================================================

def match_areas_to_uavs(
    mission: MissionInput,
    catalog: Catalog,
) -> tuple[dict[str, AreaAssignment], list[str]]:
    """Сопоставляет каждую область с бортом.

    Returns:
        (assignments, errors):
          assignments: {area_id: AreaAssignment}
          errors: список текстовых ошибок (несовместимости и т.п.).
    """
    assignments: dict[str, AreaAssignment] = {}
    errors: list[str] = []

    # Счётчик назначенных областей на борт — для балансировки
    assigned_count: dict[str, int] = {u.id: 0 for u in mission.uavs}

    for area in mission.areas:
        gsd = area.gsd_cm_per_px or mission.params.gsd_cm_per_px

        # --- 1. Жёсткая привязка ---
        if area.uav_id is not None:
            uav = _find_uav(mission, area.uav_id)
            if uav is None:
                errors.append(
                    f"Area {area.id}: uav_id={area.uav_id!r} не найден"
                )
                continue

            ok, vpp, reason = _uav_is_compatible(
                uav, area, mission, catalog,
            )
            if not ok:
                errors.append(
                    f"Area {area.id}: жёсткая привязка к {uav.id!r} "
                    f"невозможна — {reason}"
                )
                continue

            assignments[area.id] = AreaAssignment(
                area_id=area.id,
                uav_id=uav.id,
                vpp_id=vpp.id,
                camera_id=uav.camera_id,
                gsd_cm_per_px=gsd,
                survey_type=area.survey_type,
                distance_to_vpp_m=_distance_area_to_vpp(area, vpp),
            )
            assigned_count[uav.id] += 1
            continue

        # --- 2. Авто-матчинг ---
        candidates = _find_compatible_uavs(mission, catalog, area)
        if not candidates:
            errors.append(
                f"Area {area.id}: нет совместимого борта для "
                f"survey_type={area.survey_type.value!r}"
            )
            continue

        # Сортируем по score: расстояние + штраф за загрузку
        def _score(pair: tuple[UAVConfig, VPP]) -> float:
            uav, vpp = pair
            dist = _distance_area_to_vpp(area, vpp)
            return dist + BALANCE_PENALTY_M * assigned_count[uav.id]

        candidates.sort(key=_score)
        chosen_uav, chosen_vpp = candidates[0]

        assignments[area.id] = AreaAssignment(
            area_id=area.id,
            uav_id=chosen_uav.id,
            vpp_id=chosen_vpp.id,
            camera_id=chosen_uav.camera_id,
            gsd_cm_per_px=gsd,
            survey_type=area.survey_type,
            distance_to_vpp_m=_distance_area_to_vpp(area, chosen_vpp),
        )
        assigned_count[chosen_uav.id] += 1

    return assignments, errors


# ============================================================
# Хелперы
# ============================================================

def _find_uav(mission: MissionInput, uav_id: str) -> UAVConfig | None:
    for u in mission.uavs:
        if u.id == uav_id:
            return u
    return None


# ============================================================
# Сводка назначений
# ============================================================

def summarize_assignments(
    assignments: dict[str, AreaAssignment],
    mission: MissionInput,
) -> str:
    """Человекочитаемая сводка."""
    by_uav: dict[str, list[AreaAssignment]] = {u.id: [] for u in mission.uavs}
    for a in assignments.values():
        by_uav[a.uav_id].append(a)

    lines: list[str] = []
    for uav_id, items in by_uav.items():
        if not items:
            continue
        area_list = ", ".join(
            f"{a.area_id}(d={a.distance_to_vpp_m:.0f}m)" for a in items
        )
        lines.append(f"  {uav_id}: {len(items)} area(s) — {area_list}")
    return "\n".join(lines) if lines else "  (no assignments)"