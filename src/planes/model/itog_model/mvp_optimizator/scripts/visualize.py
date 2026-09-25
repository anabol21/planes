"""Folium-визуализация маршрутов с градиентом по высоте.

Запуск:
    python3 scripts/visualize.py tests/fixtures out/routes.html
"""

from __future__ import annotations

import sys
from pathlib import Path

import folium
import matplotlib
matplotlib.use("Agg")  # без GUI backend
import matplotlib.cm as cm
import matplotlib.colors as mcolors

from planner.io import load_mission
from planner.io.catalog import get_default_catalog
from planner.geometry.generate import generate_swaths_for_area


# ============================================================
# Цвета
# ============================================================

UAV_COLORS = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue"]


def gradient_color(h: float, h_min: float, h_max: float) -> str:
    """HEX-цвет по высоте: синий → зелёный → жёлтый."""
    if h_max - h_min < 1e-6:
        return "#3388ff"
    norm = (h - h_min) / (h_max - h_min)
    cmap = cm.get_cmap("viridis")
    rgba = cmap(norm)
    return mcolors.to_hex(rgba[:3])


# ============================================================
# Карта
# ============================================================

def build_map(mission, swaths_by_id: dict, candidate) -> folium.Map:
    """Собирает folium.Map со всеми слоями."""

    vpp0 = mission.vpps[0]
    m = folium.Map(
        location=[vpp0.lat, vpp0.lon],
        zoom_start=15,
        tiles=None,
    )

    # Подложки
    folium.TileLayer("OpenStreetMap", name="Схема").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Спутник",
    ).add_to(m)

    # --- Области ---
    fg_areas = folium.FeatureGroup(name="Области", show=True)
    for area in mission.areas:
        coords = area.polygon["coordinates"][0]
        latlngs = [(pt[1], pt[0]) for pt in coords]
        folium.Polygon(
            locations=latlngs,
            color="orange",
            weight=2,
            fill=True,
            fill_color="yellow",
            fill_opacity=0.15,
            popup=f"Area: {area.id}<br>Type: {area.survey_type.value}",
            tooltip=area.id,
        ).add_to(fg_areas)
    fg_areas.add_to(m)

    # --- Препятствия ---
    fg_obs = folium.FeatureGroup(name="Препятствия", show=True)
    for obs in mission.obstacles:
        coords = obs.polygon["coordinates"][0]
        latlngs = [(pt[1], pt[0]) for pt in coords]
        folium.Polygon(
            locations=latlngs,
            color="red",
            weight=2,
            fill=True,
            fill_color="red",
            fill_opacity=0.3,
            popup=f"{obs.id}<br>height={obs.height_m} m",
            tooltip=f"{obs.id} ({obs.height_m} m)",
        ).add_to(fg_obs)
    fg_obs.add_to(m)

    # --- ВПП ---
    fg_vpp = folium.FeatureGroup(name="ВПП", show=True)
    for vpp in mission.vpps:
        folium.Marker(
            location=[vpp.lat, vpp.lon],
            popup=f"VPP: {vpp.id}",
            tooltip=vpp.id,
            icon=folium.Icon(color="green", icon="home", prefix="fa"),
        ).add_to(fg_vpp)
    fg_vpp.add_to(m)

    # --- Полосы с градиентом по высоте ---
    if swaths_by_id:
        h_values = [s.h_asl_m for s in swaths_by_id.values()]
        h_min, h_max = min(h_values), max(h_values)

        fg_swaths = folium.FeatureGroup(name="Полосы (высота)", show=True)
        for swath in swaths_by_id.values():
            color = gradient_color(swath.h_asl_m, h_min, h_max)
            popup_html = (
                f"<b>{swath.id}</b><br>"
                f"h_agl = {swath.h_agl_m:.1f} m<br>"
                f"h_asl = {swath.h_asl_m:.1f} m<br>"
                f"length = {swath.length_m:.1f} m"
            )
            folium.PolyLine(
                locations=[
                    (swath.start.lat, swath.start.lon),
                    (swath.end.lat, swath.end.lon),
                ],
                color=color,
                weight=4,
                opacity=0.85,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=swath.id,
            ).add_to(fg_swaths)
        fg_swaths.add_to(m)

        # Легенда высот
        legend_html = _make_legend(h_min, h_max)
        m.get_root().html.add_child(folium.Element(legend_html))

    # --- Маршруты по бортам ---
    by_uav: dict[str, list] = {}
    for r in candidate.routes:
        by_uav.setdefault(r.uav_id, []).append(r)

    for idx, (uav_id, routes) in enumerate(by_uav.items()):
        color = UAV_COLORS[idx % len(UAV_COLORS)]
        fg = folium.FeatureGroup(name=f"Маршрут: {uav_id}", show=True)

        for r in sorted(routes, key=lambda x: x.flight_index):
            vpp = mission.vpp_by_id(r.vpp_id)
            points = [(vpp.lat, vpp.lon)]

            for k, sid in enumerate(r.swath_ids):
                s = swaths_by_id.get(sid)
                if s is None:
                    continue
                points.append((s.start.lat, s.start.lon))
                points.append((s.end.lat, s.end.lon))

                # Номер полосы в маршруте
                mid_lat = (s.start.lat + s.end.lat) / 2
                mid_lon = (s.start.lon + s.end.lon) / 2
                folium.Marker(
                    location=[mid_lat, mid_lon],
                    icon=folium.DivIcon(
                        html=(
                            f'<div style="font-size:11px;color:black;'
                            f'background:white;border:2px solid {color};'
                            f'border-radius:50%;width:18px;height:18px;'
                            f'text-align:center;line-height:18px;'
                            f'font-weight:bold;">{k + 1}</div>'
                        ),
                        icon_size=(18, 18),
                        icon_anchor=(9, 9),
                    ),
                    tooltip=f"Swath #{k + 1}: {sid}",
                ).add_to(fg)

            points.append((vpp.lat, vpp.lon))

            popup_html = (
                f"<b>{uav_id} — вылет {r.flight_index}</b><br>"
                f"Полос: {len(r.swath_ids)}<br>"
                f"T_air = {r.T_air_s:.1f} s<br>"
                f"T_total = {r.T_total_s:.1f} s<br>"
                f"E = {r.E_wh:.2f} Wh"
            )
            folium.PolyLine(
                locations=points,
                color=color,
                weight=3,
                opacity=0.85,
                dash_array="8 4",
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{uav_id} — вылет {r.flight_index}",
            ).add_to(fg)

        fg.add_to(m)

    # Переключатель слоёв
    folium.LayerControl(collapsed=False).add_to(m)

    return m


def _make_legend(h_min: float, h_max: float) -> str:
    """HTML-легенда градиента высот (правый нижний угол)."""
    return f"""
    <div style="position: fixed;
                bottom: 30px; right: 30px;
                width: 180px; height: 100px;
                background: white;
                border: 2px solid #888;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-family: sans-serif;
                z-index: 9999;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
      <div style="text-align:center; font-weight:bold;">Высота полос, м</div>
      <div style="margin-top:6px; height:16px;
                  background: linear-gradient(to right,
                    #440154, #31688e, #35b779, #fde725);
                  border-radius: 3px;"></div>
      <div style="display:flex; justify-content:space-between; margin-top:3px;">
        <span>{h_min:.0f}</span>
        <span>{(h_min + h_max) / 2:.0f}</span>
        <span>{h_max:.0f}</span>
      </div>
      <div style="text-align:center; margin-top:6px; color:#555; font-size:11px;">
        h_asl = DEM + AGL
      </div>
    </div>
    """


# ============================================================
# Main
# ============================================================

def main(fixtures_dir: str, out_html: str) -> None:
    print(f"Loading mission from {fixtures_dir}...")
    mission = load_mission(fixtures_dir)

    catalog = get_default_catalog()
    uav = mission.uavs[0]
    cam = catalog.get_camera(uav.camera_id)

    # Прогоняем pipeline — получаем лучшего кандидата
    print("Running pipeline...")
    from planner.solver.pipeline import (
        Counters,
        _generate_all_swaths,
        run_one_angle,
        select_best,
    )

    counters = Counters()
    candidates = []
    best_swaths_by_id: dict = {}
    best_theta_swaths: dict = {}

    for theta in mission.params.angles_deg:
        counters.reset_attempts()
        swaths_by_area, h_agl_by_area = _generate_all_swaths(mission, theta)
        swaths_for_this_theta = {
            s.id: s for sw in swaths_by_area.values() for s in sw
        }

        cand = run_one_angle(
            mission=mission,
            angle_deg=theta,
            counters=counters,
            swaths_by_area=swaths_by_area,
            h_agl_by_area=h_agl_by_area,
        )
        if cand is not None:
            candidates.append(cand)
            best_theta_swaths[cand.theta_deg] = swaths_for_this_theta

    if not candidates:
        print("No candidates found!")
        sys.exit(1)

    best = select_best(candidates, mission.params.optimization_criterion)
    swaths_by_id = best_theta_swaths.get(best.theta_deg, {})

    print(f"Best theta: {best.theta_deg}°, C_max: {best.C_max_s:.1f}s, "
          f"swaths total: {len(swaths_by_id)}")

    # Собираем карту
    print("Building map...")
    m = build_map(mission, swaths_by_id, best)

    # Сохраняем
    out_path = Path(out_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"Map saved: {out_path.resolve()}")


if __name__ == "__main__":
    fixtures = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"
    out_html = sys.argv[2] if len(sys.argv) > 2 else "out/routes.html"
    main(fixtures, out_html)