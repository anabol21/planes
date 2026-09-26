"""Основной конвейер: от MissionInput до Report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from planner.geometry.generate import generate_swaths_for_area
from planner.io.catalog import get_default_catalog
from planner.io.loaders import load_mission
from planner.models import (
    Candidate,
    Criterion,
    MissionInput,
    Params,
    Point,
    Report,
    Route,
    UAVSummary,
    Metrics,
)
from planner.physics import build_physics_model, build_physics_params
from planner.physics.base import PhysicsParams
from planner.solver.assignment import assign_clusters_to_uavs
from planner.solver.clustering import cluster_swaths
from planner.solver.counters import Counters
from planner.solver.multi_flight import solve_multi_flight
from planner.solver.obstacles import prepare_obstacles_m, shortest_path_avoiding
from planner.solver.routing import RoutingResult
from planner.utils.geo import make_local_transformer
from planner.validator import validate


@dataclass
class MissionContext:
    mission: MissionInput
    catalog: object
    swaths_by_area: dict[str, list]
    h_agl_by_area: dict[str, float]
    params_by_uav: dict[str, PhysicsParams]


# ============================================================
# Генерация полос
# ============================================================

def _generate_all_swaths(
    mission: MissionInput,
    angle_deg: float,
) -> tuple[dict[str, list], dict[str, float]]:
    catalog = get_default_catalog()
    uav = mission.uavs[0]
    camera = catalog.get_camera(uav.camera_id)

    pp = build_physics_params(
        uav, catalog, reserve_fraction=mission.params.reserve_fraction
    )
    model = build_physics_model(pp)
    P_nominal = model.power_w(pp.v_air_mps, mission.params.wind.speed_mps)

    swaths_by_area: dict[str, list] = {}
    h_agl_by_area: dict[str, float] = {}

    for area in mission.areas:
        swaths, h_agl = generate_swaths_for_area(
            area=area,
            obstacles=mission.obstacles,
            angle_deg=angle_deg,
            gsd_cm_per_px=mission.params.gsd_cm_per_px,
            camera=camera,
            decomposition=mission.params.decomposition.value,
            dem=mission.dem,
            v_climb_mps=pp.v_climb_mps,
            v_descent_mps=pp.v_descent_mps,
            v_min_mps=pp.v_min_mps,
            v_survey_mps=pp.v_survey_mps,
            mass_kg=pp.mass_kg,
            P_nominal_w=P_nominal,
            terrain_sample_step_m=mission.params.terrain_sample_step_m,
        )
        swaths_by_area[area.id] = swaths
        h_agl_by_area[area.id] = h_agl

    return swaths_by_area, h_agl_by_area


# ============================================================
# Маршрутизация одного борта
# ============================================================

def _solve_for_uav(
    uav_id: str,
    swath_ids: list[str],
    swaths_by_id: dict,
    vpp,
    fwd,
    physics,
    params: PhysicsParams,
    wind_speed_mps: float,
    wind_direction_deg: float,
    h_agl_m: float,
    R_max: int,
    obstacles_m: list,
) -> list[RoutingResult]:
    swaths = [swaths_by_id[sid] for sid in swath_ids]
    return solve_multi_flight(
        uav_id=uav_id,
        swaths=swaths,
        vpp=vpp,
        fwd=fwd,
        physics=physics,
        params=params,
        wind_speed_mps=wind_speed_mps,
        wind_direction_deg=wind_direction_deg,
        h_agl_m=h_agl_m,
        R_max=R_max,
        obstacles_m=obstacles_m,
    )


# ============================================================
# Waypoints с обходом и плавным набором высоты
# ============================================================

def _append_transition(
    waypoints: list[Point],
    wps_xy: list[tuple[float, float]],
    h_from: float,
    h_to: float,
    inv,
) -> None:
    """
    Добавляет waypoints перехода с линейной интерполяцией высоты
    от h_from к h_to вдоль всего пути (обход + набор/сброс высоты).
    Первая точка wps_xy пропускается (она совпадает с предыдущей).
    """
    if len(wps_xy) < 2:
        return

    # Накопленные расстояния
    cum_d = [0.0]
    for k in range(len(wps_xy) - 1):
        dx = wps_xy[k + 1][0] - wps_xy[k][0]
        dy = wps_xy[k + 1][1] - wps_xy[k][1]
        cum_d.append(cum_d[-1] + float(np.hypot(dx, dy)))

    total_d = cum_d[-1]
    if total_d < 1e-6:
        return

    for k in range(1, len(wps_xy)):
        t = cum_d[k] / total_d
        h = h_from + (h_to - h_from) * t
        lon, lat = inv.transform(wps_xy[k][0], wps_xy[k][1])
        waypoints.append(Point(lat=lat, lon=lon, alt_m=h))


def _compute_route_waypoints(
    swath_ids: list[str],
    swaths_by_id: dict,
    vpp,
    fwd,
    inv,
    obstacles_m: list,
) -> list[Point]:
    """
    Полный полётный путь в WGS84:
    VPP → (обход + набор) → swath_0 (по сегментам) → (обход + набор)
        → swath_1 → ... → VPP
    """
    vpp_xy = fwd.transform(vpp.lon, vpp.lat)
    waypoints: list[Point] = [
        Point(lat=vpp.lat, lon=vpp.lon, alt_m=vpp.alt_m)
    ]

    prev_xy = vpp_xy
    prev_h = vpp.alt_m

    for sid in swath_ids:
        s = swaths_by_id.get(sid)
        if s is None:
            continue

        # 1. Перелёт до входа в полосу
        entry_xy = fwd.transform(s.start.lon, s.start.lat)
        h_entry = s.h_asl_entry_m or s.h_asl_m

        _, wps = shortest_path_avoiding(prev_xy, entry_xy, obstacles_m)
        _append_transition(waypoints, wps, prev_h, h_entry, inv)

        # 2. Проход по полосе — по сегментам (профиль высоты)
        if s.segments and len(s.segments) >= 2:
            for seg in s.segments:
                waypoints.append(Point(lat=seg.lat, lon=seg.lon,
                                       alt_m=seg.h_asl_m))
        else:
            waypoints.append(Point(lat=s.start.lat, lon=s.start.lon,
                                   alt_m=s.h_asl_entry_m or s.h_asl_m))
            waypoints.append(Point(lat=s.end.lat, lon=s.end.lon,
                                   alt_m=s.h_asl_exit_m or s.h_asl_m))

        prev_xy = fwd.transform(s.end.lon, s.end.lat)
        prev_h = s.h_asl_exit_m or s.h_asl_m

    # 3. Возврат на VPP
    _, wps = shortest_path_avoiding(prev_xy, vpp_xy, obstacles_m)
    _append_transition(waypoints, wps, prev_h, vpp.alt_m, inv)

    return waypoints


# ============================================================
# Candidate
# ============================================================

def _build_candidate(
    theta_deg: float,
    all_routes: list[Route],
    decomposition_method: str,
) -> Candidate | None:
    if not all_routes:
        return None

    by_uav: dict[str, list[Route]] = {}
    for r in all_routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    C_max_per_uav: list[float] = []
    for uav_id, routes in by_uav.items():
        sorted_r = sorted(routes, key=lambda x: x.flight_index)
        T_charge = sorted_r[0].T_charge_s if sorted_r else 0.0
        total = sum(r.T_total_s for r in sorted_r)
        total += max(0, len(sorted_r) - 1) * T_charge
        C_max_per_uav.append(total)

    return Candidate(
        theta_deg=theta_deg,
        C_max_s=max(C_max_per_uav) if C_max_per_uav else 0.0,
        flight_hours_s=sum(r.T_air_s for r in all_routes),
        energy_total_wh=sum(r.E_wh for r in all_routes),
        n_uavs_used=len(by_uav),
        routes=all_routes,
        decomposition_method=decomposition_method,
    )


# ============================================================
# Прогон одного угла
# ============================================================

def run_one_angle(
    mission: MissionInput,
    angle_deg: float,
    counters: Counters,
    swaths_by_area: dict[str, list] | None = None,
    h_agl_by_area: dict[str, float] | None = None,
) -> Candidate | None:
    catalog = get_default_catalog()

    if swaths_by_area is None or h_agl_by_area is None:
        swaths_by_area, h_agl_by_area = _generate_all_swaths(mission, angle_deg)

    all_swaths = [s for sw in swaths_by_area.values() for s in sw]
    if not all_swaths:
        return None

    swaths_by_id = {s.id: s for s in all_swaths}

    # Кластеризация + назначение
    clusters = cluster_swaths(all_swaths, k=len(mission.uavs))
    assign = assign_clusters_to_uavs(clusters, mission.uavs, mission.vpps)

    # Физика по бортам
    params_by_uav: dict[str, PhysicsParams] = {}
    physics_by_uav = {}
    for uav in mission.uavs:
        pp = build_physics_params(
            uav, catalog, reserve_fraction=mission.params.reserve_fraction
        )
        params_by_uav[uav.id] = pp
        physics_by_uav[uav.id] = build_physics_model(pp)

    all_routes: list[Route] = []
    wind_speed = mission.params.wind.speed_mps
    wind_dir = mission.params.wind.direction_deg
    h_agl_m = sum(h_agl_by_area.values()) / max(len(h_agl_by_area), 1)

    for uav in mission.uavs:
        uav_clusters = assign.get(uav.id, [])
        swath_ids = [sid for c in uav_clusters for sid in c.swath_ids]
        if not swath_ids:
            continue

        vpp = mission.vpp_by_id(uav.vpp_id)
        fwd, inv = make_local_transformer(vpp.lon, vpp.lat)

        obs_geojsons = [o.polygon for o in mission.obstacles]
        obstacles_m = prepare_obstacles_m(obs_geojsons, fwd)

        results = _solve_for_uav(
            uav_id=uav.id,
            swath_ids=swath_ids,
            swaths_by_id=swaths_by_id,
            vpp=vpp,
            fwd=fwd,
            physics=physics_by_uav[uav.id],
            params=params_by_uav[uav.id],
            wind_speed_mps=wind_speed,
            wind_direction_deg=wind_dir,
            h_agl_m=h_agl_m,
            R_max=mission.params.R_max,
            obstacles_m=obstacles_m,
        )

        T_charge = params_by_uav[uav.id].T_charge_s

        for i, res in enumerate(results):
            waypoints = _compute_route_waypoints(
                swath_ids=res.swath_ids,
                swaths_by_id=swaths_by_id,
                vpp=vpp,
                fwd=fwd,
                inv=inv,
                obstacles_m=obstacles_m,
            )
            all_routes.append(Route(
                uav_id=uav.id,
                flight_index=i,
                vpp_id=res.vpp_id,
                swath_ids=res.swath_ids,
                T_air_s=res.T_air_s,
                T_total_s=res.T_total_s,
                E_wh=res.E_wh,
                mass_kg=params_by_uav[uav.id].mass_kg,
                T_charge_s=T_charge,
                waypoints=waypoints,
            ))

    if not all_routes:
        return None

    result = validate(
        mission=mission,
        all_swaths=all_swaths,
        routes=all_routes,
        params_by_uav=params_by_uav,
    )

    if not result.valid:
        counters.inc_attempts()
        return None

    return _build_candidate(angle_deg, all_routes,
                            mission.params.decomposition.value)


# ============================================================
# Выбор лучшего, LNS
# ============================================================

def select_best(candidates: list[Candidate], criterion: Criterion) -> Candidate:
    if not candidates:
        raise ValueError("No candidates")
    key = (lambda c: c.C_max_s) if criterion == Criterion.MIN_TIME else (
        lambda c: c.flight_hours_s)
    return min(candidates, key=key)


def lns_improve(candidate, mission, counters, max_iters):
    return candidate


# ============================================================
# Полный прогон
# ============================================================

def run_mission(fixtures_dir: str | Path, output_dir: str | Path) -> Report:
    mission = load_mission(fixtures_dir)
    counters = Counters()
    candidates: list[Candidate] = []
    last_swaths_by_id: dict = {}

    for theta in mission.params.angles_deg:
        counters.reset_attempts()
        swaths_by_area, h_agl_by_area = _generate_all_swaths(mission, theta)
        last_swaths_by_id = {
            s.id: s for sw in swaths_by_area.values() for s in sw
        }

        for _ in range(mission.params.attempts_max):
            cand = run_one_angle(
                mission=mission,
                angle_deg=theta,
                counters=counters,
                swaths_by_area=swaths_by_area,
                h_agl_by_area=h_agl_by_area,
            )
            if cand is not None:
                candidates.append(cand)
                break

    if not candidates:
        raise RuntimeError("No valid candidates found")

    best = select_best(candidates, mission.params.optimization_criterion)
    best = lns_improve(best, mission, counters, mission.params.iter_max)

    per_uav: dict[str, UAVSummary] = {}
    for r in best.routes:
        if r.uav_id not in per_uav:
            per_uav[r.uav_id] = UAVSummary(
                uav_id=r.uav_id, n_flights=0,
                T_air_s=0.0, T_total_s=0.0, E_wh=0.0,
                mass_kg=r.mass_kg, T_charge_s=r.T_charge_s,
            )
        s = per_uav[r.uav_id]
        s.n_flights += 1
        s.T_air_s += r.T_air_s
        s.T_total_s += r.T_total_s
        s.E_wh += r.E_wh

    for s in per_uav.values():
        s.T_mission_s = s.T_total_s + max(0, s.n_flights - 1) * s.T_charge_s

    metrics = Metrics(
        C_max_s=best.C_max_s,
        flight_hours_total_s=best.flight_hours_s,
        energy_total_wh=best.energy_total_wh,
        n_uavs_used=best.n_uavs_used,
        n_swaths_total=sum(len(r.swath_ids) for r in best.routes),
    )

    report = Report(
        mission_id="mvp",
        theta_best_deg=best.theta_deg,
        decomposition_method=best.decomposition_method,
        optimization_criterion=mission.params.optimization_criterion.value,
        metrics=metrics,
        per_uav=list(per_uav.values()),
        n_angles_tried=len(mission.params.angles_deg),
        n_candidates=len(candidates),
        lns_iterations=counters.lns_iter,
    )

    from planner.io.json_out import write_report_json
    from planner.io.kml_out import write_routes_kml

    out = Path(output_dir) / "mission"
    out.mkdir(parents=True, exist_ok=True)

    write_report_json(out / "report.json", report)
    write_routes_kml(
        out / "routes.kml",
        mission=mission,
        candidate=best,
        swaths_by_id=last_swaths_by_id,
    )

    return report
