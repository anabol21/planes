"""Экспорт маршрутов и полос в KML."""

from __future__ import annotations

from pathlib import Path

import simplekml

from planner.models import Candidate, MissionInput, Swath, VPP


# Цвета для разных бортов (AABBGGRR)
_UAV_COLORS = [
    "ff0000ff",  # красный
    "ff00ff00",  # зелёный
    "ffff0000",  # синий
    "ff00ffff",  # жёлтый
    "ffff00ff",  # magenta
    "ff8080ff",  # оранжевый
    "ff00aaff",  # оранжево-жёлтый
    "ffff8000",  # голубой
]


def _uav_color(index: int) -> str:
    """Возвращает цвет для i-го борта, циклом."""
    return _UAV_COLORS[index % len(_UAV_COLORS)]


def _add_vpp(kml: simplekml.Kml, vpp: VPP) -> None:
    """Добавляет точку ВПП с иконкой."""
    p = kml.newpoint(
        name=f"VPP: {vpp.id}",
        description=f"alt={vpp.alt_m} m",
        coords=[(vpp.lon, vpp.lat, vpp.alt_m)],
    )
    p.style.iconstyle.color = "ff00ff00"   # зелёный
    p.style.iconstyle.scale = 1.2
    p.style.labelstyle.scale = 1.0


def _add_swath(kml: simplekml.Kml, swath: Swath, color: str) -> None:
    """Добавляет одну полосу как LineString."""
    ls = kml.newlinestring(
        name=swath.id,
        coords=[
            (swath.start.lon, swath.start.lat, swath.start.alt_m),
            (swath.end.lon, swath.end.lat, swath.end.alt_m),
        ],
    )
    ls.style.linestyle.color = color
    ls.style.linestyle.width = 2
    ls.altitudemode = simplekml.AltitudeMode.clamptoground


def _add_route(
    kml: simplekml.Kml,
    candidate: Candidate,
    vpp: VPP,
    swaths_by_id: dict[str, Swath],
) -> None:
    """
    Каждый борт — папка с линиями маршрута по вылетам.

    Полный маршрут:
        ВПП → swath_1.start → swath_1.end
            → swath_2.start → swath_2.end
            → ...
            → ВПП
    """
    by_uav: dict[str, list] = {}
    for r in candidate.routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    for idx, (uav_id, routes) in enumerate(by_uav.items()):
        color = _uav_color(idx)
        folder = kml.newfolder(name=f"UAV: {uav_id}")

        for r in sorted(routes, key=lambda x: x.flight_index):
            coords: list[tuple[float, float, float]] = [
                (vpp.lon, vpp.lat, vpp.alt_m)
            ]

            for sid in r.swath_ids:
                s = swaths_by_id.get(sid)
                if s is None:
                    continue
                coords.append((s.start.lon, s.start.lat, s.start.alt_m))
                coords.append((s.end.lon, s.end.lat, s.end.alt_m))

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
            ls.altitudemode = simplekml.AltitudeMode.clamptoground
            ls.description = (
                f"Swaths: {len(r.swath_ids)}\n"
                f"T_air = {r.T_air_s:.1f} s\n"
                f"T_total = {r.T_total_s:.1f} s\n"
                f"E = {r.E_wh:.2f} Wh\n"
                f"m = {r.mass_kg:.2f} kg"
            )


def write_routes_kml(
    path: str | Path,
    mission: MissionInput,
    candidate: Candidate,
    swaths_by_id: dict[str, Swath] | None = None,
) -> None:
    """
    Пишет KML:
      - все ВПП
      - все полосы (серые, отдельная папка)
      - маршруты по бортам (цветные)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml(name="Geoscan Planner — routes")

    # --- ВПП ---
    for vpp in mission.vpps:
        _add_vpp(kml, vpp)

    # --- Полосы (серые) ---
    if swaths_by_id:
        folder = kml.newfolder(name="Swaths")
        for swath in swaths_by_id.values():
            ls = folder.newlinestring(
                name=swath.id,
                coords=[
                    (swath.start.lon, swath.start.lat, swath.start.alt_m),
                    (swath.end.lon, swath.end.lat, swath.end.alt_m),
                ],
            )
            ls.style.linestyle.color = "ff888888"
            ls.style.linestyle.width = 1
            ls.altitudemode = simplekml.AltitudeMode.clamptoground

    # --- Маршруты ---
    if mission.vpps:
        vpp = mission.vpps[0]
        _add_route(kml, candidate, vpp, swaths_by_id or {})

    kml.save(str(path))