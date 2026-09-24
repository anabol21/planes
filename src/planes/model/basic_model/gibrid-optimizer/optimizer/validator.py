"""Проверка корректности решения."""

from typing import Any, Dict, List

from .models import InputData


def validate(
    result: Dict[str, Any],
    routes: List[Dict[str, Any]],
    pre: Dict[str, Any],
    input_data: InputData,
) -> Dict[str, bool]:
    M = pre["M"]
    T_max = pre["T_max"]
    E_max = pre["E_max"]
    T_takeoff = pre["T_takeoff"]
    T_landing = pre["T_landing"]
    E_takeoff = pre["E_takeoff"]
    E_landing = pre["E_landing"]

    # 1. покрытие полос без дублей
    all_strips = set(range(M))
    covered = set()
    duplicate = False
    for r in routes:
        for s in r["strips"]:
            if s in covered:
                duplicate = True
            covered.add(s)

    # 2. бюджет времени и энергии
    time_ok = True
    energy_ok = True
    for r in routes:
        t_mission = r["time_breakdown_s"]["total"] - T_takeoff - T_landing
        if t_mission > T_max + 1e-6:
            time_ok = False
        e_mission = r["energy_breakdown_wh"]["total"] - E_takeoff - E_landing
        if e_mission > E_max + 1e-6:
            energy_ok = False

    # 3. каждый маршрут начинается взлётом и заканчивается посадкой
    returned = all(
        r["waypoints"][0]["type"] == "takeoff"
        and r["waypoints"][-1]["type"] == "landing"
        for r in routes
    )

    # 4. использовано не больше доступных бортов
    uav_count_ok = len(routes) <= input_data.uav.count

    # 5. борта пронумерованы без пропусков
    used_ids = sorted(r["uav_id"] for r in routes)
    uav_ids_contiguous = used_ids == list(range(len(used_ids)))

    # 6. нет пустых маршрутов
    no_empty_routes = all(len(r["strips"]) > 0 for r in routes)

    return {
        "all_strips_covered": covered == all_strips,
        "no_duplicate_strips": not duplicate,
        "time_ok": time_ok,
        "energy_ok": energy_ok,
        "returned_to_base": returned,
        "uav_count_ok": uav_count_ok,
        "uav_ids_contiguous": uav_ids_contiguous,
        "no_empty_routes": no_empty_routes,
    }