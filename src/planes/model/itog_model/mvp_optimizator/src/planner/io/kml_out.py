"""Экспорт маршрутов и полос в KML (с профилем высоты и обходом)."""

from __future__ import annotations

from pathlib import Path

import simplekml

from planner.models import Candidate, MissionInput, Swath, VPP


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
    """Рисует полосу с профилем высоты (по сегментам)."""
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
        f"h_asl entry = {swath.h_asl_entry_m:.1f} m<br>"
        f"h_asl exit = {swath.h_asl_exit_m:.1f} m<br>"
        f"DEM: {swath.dem_min_m:.0f}..{swath.dem_max_m:.0f} m<br>"
        f"h_agl min = {swath.h_agl_min_m:.1f} m<br>"
        f"length = {swath.length_m:.0f} m"
    )


def _add_route(
    kml: simplekml.Kml,
    candidate: Candidate,
    vpp: VPP,
    swaths_by_id: dict[str, Swath],
) -> None:
    """
    Каждый борт — папка с линиями маршрута.
    Если у Route есть waypoints — используем их (с обходом препятствий).
    """
    by_uav: dict[str, list] = {}
    for r in candidate.routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    for idx, (uav_id, routes) in enumerate(by_uav.items()):
        color = _uav_color(idx)
        folder = kml.newfolder(name=f"UAV: {uav_id}")

        for r in sorted(routes, key=lambda x: x.flight_index):
            # NEW: если есть waypoints — рисуем их
            if getattr(r, "waypoints", None):
                coords = [(p.lon, p.lat, p.alt_m) for p in r.waypoints]
            else:
                # fallback: старое поведение
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
                f"Swaths: {len(r.swath_ids)}<br>"
                f"T_air = {r.T_air_s:.1f} s<br>"
                f"T_total = {r.T_total_s:.1f} s<br>"
                f"E = {r.E_wh:.2f} Wh<br>"
                f"m = {r.mass_kg:.2f} kg<br>"
                f"climb = {r.total_climb_m:.0f} m, "
                f"descent = {r.total_descent_m:.0f} m<br>"
                f"ASL: {r.h_asl_min_m:.0f}..{r.h_asl_max_m:.0f} m"
            )


def write_routes_kml(
    path: str | Path,
    mission: MissionInput,
    candidate: Candidate,
    swaths_by_id: dict[str, Swath] | None = None,
) -> None:
    """
    Пишет KML:
      - ВПП,
      - полосы (папка Swaths) — с профилем высоты,
      - маршруты по бортам — с обходом препятствий (по waypoints).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml(name="Geoscan Planner — routes")

    for vpp in mission.vpps:
        _add_vpp(kml, vpp)

    if swaths_by_id:
        folder = kml.newfolder(name="Swaths")
        for swath in swaths_by_id.values():
            _add_swath(folder, swath, color="ff888888")

    if mission.vpps:
        vpp = mission.vpps[0]
        _add_route(kml, candidate, vpp, swaths_by_id or {})

    kml.save(str(path))