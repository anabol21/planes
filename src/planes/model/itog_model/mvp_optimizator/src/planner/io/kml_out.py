"""Экспорт маршрутов и полос в KML (с профилем высоты и обходом).

Слои KML:
  - VPP (зелёные маркеры);
  - Swaths (тонкие серые линии — полосы);
  - Obstacles (красные полигоны — препятствия);
  - NoFlyZones (красные полупрозрачные полигоны — запретные зоны);
  - UAV: <id> (папки с маршрутами по бортам).
"""

from __future__ import annotations

from pathlib import Path

import simplekml

from planner.models import (
    Candidate,
    MissionInput,
    Obstacle,
    NoFlyZone,
    Swath,
    VPP,
)


_UAV_COLORS = [
    "ff0000ff",   # красный
    "ff00ff00",   # зелёный
    "ffff0000",   # синий
    "ff00ffff",   # жёлтый
    "ffff00ff",   # magenta
    "ff8080ff",   # оранжевый
    "ff00aaff",   # оранжево-жёлтый
    "ffff8000",   # голубой
]


def _uav_color(index: int) -> str:
    return _UAV_COLORS[index % len(_UAV_COLORS)]


def _fmt_height(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f}"


# ============================================================
# Базовые элементы
# ============================================================

def _add_vpp(kml: simplekml.Kml, vpp: VPP) -> None:
    p = kml.newpoint(
        name=f"VPP: {vpp.id}",
        description=f"alt={vpp.alt_m} m",
        coords=[(vpp.lon, vpp.lat, vpp.alt_m)],
    )
    p.style.iconstyle.color = "ff00ff00"
    p.style.iconstyle.scale = 1.2
    p.style.labelstyle.scale = 1.0
    p.altitudemode = simplekml.AltitudeMode.absolute


def _add_swath(kml: simplekml.Kml, swath: Swath, color: str) -> None:
    if swath.segments and len(swath.segments) >= 2:
        coords = [(seg.lon, seg.lat, seg.h_asl_m) for seg in swath.segments]
    else:
        coords = [
            (swath.start.lon, swath.start.lat, swath.h_asl_m),
            (swath.end.lon, swath.end.lat, swath.h_asl_m),
        ]

    ls = kml.newlinestring(name=swath.id, coords=coords)
    ls.style.linestyle.color = color
    ls.style.linestyle.width = 3
    ls.altitudemode = simplekml.AltitudeMode.absolute
    ls.description = (
        f"h_agl = {swath.h_agl_m:.1f} m<br>"
        f"h_asl avg = {swath.h_asl_m:.1f} m<br>"
        f"h_asl entry = {_fmt_height(swath.h_asl_entry_m)} m<br>"
        f"h_asl exit = {_fmt_height(swath.h_asl_exit_m)} m<br>"
        f"DEM: {swath.dem_min_m:.0f}..{swath.dem_max_m:.0f} m<br>"
        f"h_agl min = {_fmt_height(swath.h_agl_min_m)} m<br>"
        f"length = {swath.length_m:.0f} m"
    )


def _add_obstacle(kml: simplekml.Kml, obs: Obstacle) -> None:
    """Препятствие — красный контур с полупрозрачной заливкой."""
    coords = obs.polygon["coordinates"][0]   # ring
    latlngs = [(c[0], c[1]) for c in coords]

    pol = kml.newpolygon(
        name=obs.id,
        outerboundaryis=latlngs,
    )
    pol.style.polystyle.color = "660000ff"   # красный, alpha=0x66
    pol.style.linestyle.color = "ff0000ff"
    pol.style.linestyle.width = 2
    pol.description = (
        f"<b>Препятствие</b><br>"
        f"id: {obs.id}<br>"
        f"name: {obs.name}<br>"
        f"height: {obs.height_m} м"
    )


def _add_no_fly_zone(kml: simplekml.Kml, nfz: NoFlyZone) -> None:
    """Запретная зона — красный контур, сплошная заливка."""
    coords = nfz.polygon["coordinates"][0]
    latlngs = [(c[0], c[1]) for c in coords]

    pol = kml.newpolygon(
        name=f"NFZ: {nfz.id}",
        outerboundaryis=latlngs,
    )
    # Более насыщенный красный, чем у препятствий
    pol.style.polystyle.color = "990000ff"   # alpha=0x99
    pol.style.linestyle.color = "ff0000ff"   # ярко-красный
    pol.style.linestyle.width = 3
    pol.description = (
        f"<b>ЗАПРЕТНАЯ ЗОНА</b><br>"
        f"id: {nfz.id}<br>"
        f"name: {nfz.name}<br>"
        f"полёты запрещены на любой высоте"
    )


# ============================================================
# Маршруты
# ============================================================

def _add_route(
    kml: simplekml.Kml,
    candidate: Candidate,
    mission: MissionInput,
    swaths_by_id: dict[str, Swath],
) -> None:
    by_uav: dict[str, list] = {}
    for r in candidate.routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    for idx, (uav_id, routes) in enumerate(by_uav.items()):
        color = _uav_color(idx)
        folder = kml.newfolder(name=f"UAV: {uav_id}")

        for r in sorted(routes, key=lambda x: x.flight_index):
            vpp = mission.vpp_by_id(r.vpp_id)

            if getattr(r, "waypoints", None):
                coords = [(p.lon, p.lat, p.alt_m) for p in r.waypoints]
            else:
                coords = [(vpp.lon, vpp.lat, vpp.alt_m)]
                for sid in r.swath_ids:
                    s = swaths_by_id.get(sid)
                    if s is None:
                        continue
                    if s.segments and len(s.segments) >= 2:
                        for seg in s.segments:
                            coords.append((seg.lon, seg.lat, seg.h_asl_m))
                    else:
                        coords.append((s.start.lon, s.start.lat, s.h_asl_m))
                        coords.append((s.end.lon, s.end.lat, s.h_asl_m))
                coords.append((vpp.lon, vpp.lat, vpp.alt_m))

            if len(coords) < 2:
                continue

            ls = folder.newlinestring(
                name=(
                    f"{uav_id}-flight{r.flight_index} "
                    f"(T={r.T_total_s:.0f}s, E={r.E_wh:.1f}Wh)"
                ),
                coords=coords,
            )
            ls.style.linestyle.color = color
            ls.style.linestyle.width = 3
            ls.altitudemode = simplekml.AltitudeMode.absolute
            ls.description = (
                f"VPP: {r.vpp_id}<br>"
                f"Swaths: {len(r.swath_ids)}<br>"
                f"T_air = {r.T_air_s:.1f} s<br>"
                f"T_total = {r.T_total_s:.1f} s<br>"
                f"E = {r.E_wh:.2f} Wh<br>"
                f"m = {r.mass_kg:.2f} kg<br>"
                f"climb = {r.total_climb_m:.0f} m, "
                f"descent = {r.total_descent_m:.0f} m<br>"
                f"ASL: {r.h_asl_min_m:.0f}..{r.h_asl_max_m:.0f} m<br>"
                f"waypoints: {len(getattr(r, 'waypoints', []) or [])}"
            )


# ============================================================
# Основная функция
# ============================================================

def write_routes_kml(
    path: str | Path,
    mission: MissionInput,
    candidate: Candidate,
    swaths_by_id: dict[str, Swath] | None = None,
) -> None:
    """Пишет KML:
      - VPP (зелёные маркеры);
      - Swaths (серые линии);
      - Obstacles (красные контуры);
      - NoFlyZones (красные сплошные заливки);
      - UAV: <id> (папки с маршрутами по бортам).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml(name="Geoscan Planner — routes")

    # 1. VPP
    for vpp in mission.vpps:
        _add_vpp(kml, vpp)

    # 2. Полосы
    if swaths_by_id:
        folder = kml.newfolder(name="Swaths")
        for swath in swaths_by_id.values():
            _add_swath(folder, swath, color="ff888888")

    # 3. Препятствия
    if mission.obstacles:
        obs_folder = kml.newfolder(name="Obstacles")
        for obs in mission.obstacles:
            _add_obstacle(obs_folder, obs)

    # 4. Запретные зоны
    if mission.no_fly_zones:
        nfz_folder = kml.newfolder(name="NoFlyZones")
        for nfz in mission.no_fly_zones:
            _add_no_fly_zone(nfz_folder, nfz)

    # 5. Маршруты
    _add_route(kml, candidate, mission, swaths_by_id or {})

    kml.save(str(path))