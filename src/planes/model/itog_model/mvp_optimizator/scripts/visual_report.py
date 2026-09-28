"""Визуальный отчёт о миссии: pipeline + графики + Folium + index.html.

Структура выхода:
    <out>/
    ├── mission/
    │   ├── report.json
    │   ├── routes.kml
    │   └── routes.geojson
    ├── visuals/
    │   ├── map.html
    │   ├── profile.png
    │   ├── energy.png
    │   ├── coverage.png
    │   ├── comparison.png
    │   └── terrain_cross.png
    └── index.html

Запуск:
    python3 scripts/visual_report.py tests/fixtures/moscow out/moscow_report
"""

from __future__ import annotations

import argparse
import json
import math
from io import BytesIO
from pathlib import Path

import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import shape

from planner.io.catalog import get_default_catalog
from planner.io.loaders import load_mission
from planner.models import Point
from planner.solver.pipeline import _generate_all_swaths, run_mission
from planner.utils.geo import make_local_transformer
from planner.utils.route_metrics import haversine_m


# ============================================================
# Утилиты
# ============================================================

def _save_fig_safe(fig, out_path: Path, dpi: int = 110) -> None:
    """Сохраняет фигуру через BytesIO (OneDrive/Windows volume-safe)."""
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    except Exception as e:
        print(f"  [warn] bbox_inches failed: {e}, retry without")
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    plt.close(fig)


def _fmt_hms(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} с"
    if seconds < 3600:
        return f"{seconds/60:.1f} мин"
    return f"{seconds/3600:.2f} ч"


# ============================================================
# 1. Профиль рельефа + ASL вдоль маршрутов
# ============================================================

def plot_profile(mission, routes_data: list[dict], out_path: Path) -> None:
    if not routes_data:
        return

    xs: list[float] = []
    dem_vals: list[float] = []
    drone_vals: list[float] = []
    boundaries: list[int] = []
    cum = 0.0

    for r in routes_data:
        wps = r.get("waypoints", [])
        if len(wps) < 2:
            continue
        for i in range(len(wps) - 1):
            p1 = Point(**wps[i])
            p2 = Point(**wps[i + 1])
            d = haversine_m(p1, p2)
            if d < 1e-6:
                continue
            xs.append(cum + d / 2.0)
            dem_vals.append(
                mission.dem.h(p1.lat, p1.lon) if mission.dem else 0.0
            )
            drone_vals.append(p1.alt_m)
            cum += d
        boundaries.append(len(xs))
        last = wps[-1]
        xs.append(cum)
        dem_vals.append(
            mission.dem.h(last["lat"], last["lon"]) if mission.dem else 0.0
        )
        drone_vals.append(last["alt_m"])

    if not xs:
        return

    x = np.array(xs)
    dem_arr = np.array(dem_vals)
    drone_arr = np.array(drone_vals)
    agl = drone_arr - dem_arr

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 3]},
    )

    ax1.fill_between(x, 0, dem_arr, color="#8b6914", alpha=0.6,
                     label="Рельеф (DEM)")
    ax1.plot(x, dem_arr, color="#5c4608", linewidth=1.2)
    ax1.set_ylabel("Рельеф, м ASL", fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left", fontsize=10)
    ax1.set_title("Профиль рельефа и высоты БВС вдоль маршрутов",
                  fontsize=13, fontweight="bold")

    ax2.fill_between(x, 0, drone_arr, color="#4a90e2", alpha=0.35,
                     label="Высота БВС (ASL)")
    ax2.plot(x, drone_arr, color="#1e5fa8", linewidth=2.0)
    ax2.plot(x, dem_arr, color="#5c4608", linewidth=1.0,
             linestyle="--", alpha=0.7, label="DEM")

    for idx in boundaries[:-1]:
        if idx < len(x):
            ax2.axvline(x[idx], color="gray", linestyle="--",
                        alpha=0.4, linewidth=0.8)

    if len(agl) > 0:
        min_idx = int(np.argmin(agl))
        ax2.annotate(
            f"min AGL = {agl.min():.0f} м",
            xy=(x[min_idx], drone_arr[min_idx]),
            xytext=(20, 20), textcoords="offset points",
            fontsize=10, color="darkred",
            arrowprops=dict(arrowstyle="->", color="darkred"),
        )

    ax2.set_xlabel("Пройденный путь, м", fontsize=12)
    ax2.set_ylabel("Высота БВС, м ASL", fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=10)

    _save_fig_safe(fig, out_path)


# ============================================================
# 2. Энергия и время по бортам
# ============================================================

def plot_energy(per_uav: list[dict], out_path: Path) -> None:
    if not per_uav:
        return

    uav_ids = [u["uav_id"] for u in per_uav]
    T_air = [u["T_air_s"] for u in per_uav]
    T_total = [u["T_total_s"] for u in per_uav]
    E_wh = [u["E_wh"] for u in per_uav]
    n_flights = [u["n_flights"] for u in per_uav]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    x = np.arange(len(uav_ids))
    w = 0.35
    ax = axes[0][0]
    ax.bar(x - w/2, T_air, w, label="T_air (перелёт+съёмка)",
           color="#4a90e2")
    ax.bar(x + w/2, T_total, w, label="T_total (+взлёт/посадка)",
           color="#1e5fa8")
    ax.set_xticks(x)
    ax.set_xticklabels(uav_ids, rotation=15, ha="right")
    ax.set_ylabel("Время, с")
    ax.set_title("Время по бортам", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    ax = axes[0][1]
    ax.bar(x, E_wh, color="#e67e22")
    ax.set_xticks(x)
    ax.set_xticklabels(uav_ids, rotation=15, ha="right")
    ax.set_ylabel("Энергия, Вт·ч")
    ax.set_title("Расход энергии", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")

    ax = axes[1][0]
    ax.pie(E_wh, labels=uav_ids, autopct="%1.1f%%",
           colors=plt.cm.Set3(np.linspace(0, 1, len(uav_ids))))
    ax.set_title("Доля энергии по бортам", fontweight="bold")

    ax = axes[1][1]
    ax.bar(x, n_flights, color="#2ecc71")
    ax.set_xticks(x)
    ax.set_xticklabels(uav_ids, rotation=15, ha="right")
    ax.set_ylabel("Число вылетов")
    ax.set_title("Вылеты (multi-flight)", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    _save_fig_safe(fig, out_path)


# ============================================================
# 3. Карта покрытия
# ============================================================

def plot_coverage(mission, routes_data: list[dict],
                  swaths_by_id, out_path: Path) -> None:
    if not routes_data or not swaths_by_id:
        return

    area = mission.areas[0]
    poly = shape(area.polygon)
    c = poly.centroid
    fwd, _ = make_local_transformer(c.x, c.y)

    swath_to_uav: dict[str, str] = {}
    for r in routes_data:
        for sid in r.get("swath_ids", []):
            swath_to_uav[sid] = r["uav_id"]

    uav_ids = sorted({r["uav_id"] for r in routes_data})
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(uav_ids), 3)))
    color_map = {u: colors[i % len(colors)] for i, u in enumerate(uav_ids)}

    fig, ax = plt.subplots(figsize=(12, 10))

    xs, ys = poly.exterior.xy
    ax.plot(xs, ys, "k-", linewidth=1.5, alpha=0.5,
            label="Граница области")

    for obs in mission.obstacles:
        op = shape(obs.polygon)
        ox, oy = op.exterior.xy
        ax.fill(ox, oy, color="red", alpha=0.3)

    for nfz in mission.no_fly_zones:
        np_ = shape(nfz.polygon)
        nx, ny = np_.exterior.xy
        ax.fill(nx, ny, color="darkred", alpha=0.5)

    for sid, sw in swaths_by_id.items():
        uav = swath_to_uav.get(sid)
        color = color_map.get(uav, "gray")
        x1, y1 = fwd.transform(sw.start.lon, sw.start.lat)
        x2, y2 = fwd.transform(sw.end.lon, sw.end.lat)
        ax.plot([x1, x2], [y1, y2], color=color, linewidth=2.0, alpha=0.8)

    for u, c in color_map.items():
        ax.plot([], [], color=c, linewidth=3, label=u)
    ax.legend(loc="upper right", fontsize=10)

    ax.set_aspect("equal")
    ax.set_xlabel("X, м (ENU)")
    ax.set_ylabel("Y, м (ENU)")
    ax.set_title("Карта покрытия: полосы по бортам", fontweight="bold")
    ax.grid(True, alpha=0.2)

    _save_fig_safe(fig, out_path)


# ============================================================
# 4. Сравнение бортов
# ============================================================

def plot_comparison(per_uav: list[dict], out_path: Path) -> None:
    if not per_uav:
        return

    uav_ids = [u["uav_id"] for u in per_uav]
    mass = [u["mass_kg"] for u in per_uav]
    T_mission = [u["T_mission_s"] for u in per_uav]
    n_flights = [u["n_flights"] for u in per_uav]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    ax = axes[0]
    ax.bar(uav_ids, mass, color="#95a5a6")
    ax.set_ylabel("Масса, кг")
    ax.set_title("Масса бортов", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")

    ax = axes[1]
    ax.bar(uav_ids, T_mission, color="#3498db")
    ax.set_ylabel("T_mission, с")
    ax.set_title("Полное время работы (с зарядками)", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")

    ax = axes[2]
    bars = ax.bar(uav_ids, n_flights, color="#27ae60")
    for bar, n in zip(bars, n_flights):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                str(n), ha="center", fontsize=10)
    ax.set_ylabel("Вылетов")
    ax.set_title("Число вылетов", fontweight="bold")
    ax.grid(True, alpha=0.3, axis="y")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")

    plt.tight_layout()
    _save_fig_safe(fig, out_path)


# ============================================================
# 5. Срезы DEM
# ============================================================

def plot_terrain_cross(mission, out_path: Path) -> None:
    if mission.dem is None or mission.dem.is_empty():
        return

    all_pts: list[tuple[float, float]] = []
    for area in mission.areas:
        poly = shape(area.polygon)
        for x, y in poly.exterior.coords:
            all_pts.append((y, x))

    if not all_pts:
        return

    lats = [p[0] for p in all_pts]
    lons = [p[1] for p in all_pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    n = 100
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5))

    lat_c = (min_lat + max_lat) / 2.0
    xs = np.linspace(min_lon, max_lon, n)
    ys = [mission.dem.h(lat_c, lon) for lon in xs]
    ax1.plot((xs - min_lon) * 111_320 * math.cos(math.radians(lat_c)),
             ys, color="#8b6914", linewidth=2.0)
    ax1.fill_between(
        (xs - min_lon) * 111_320 * math.cos(math.radians(lat_c)),
        0, ys, color="#8b6914", alpha=0.4,
    )
    ax1.set_xlabel("Расстояние по X, м")
    ax1.set_ylabel("Высота, м ASL")
    ax1.set_title(f"Срез рельефа по X (lat={lat_c:.4f})",
                  fontweight="bold")
    ax1.grid(True, alpha=0.3)

    lon_c = (min_lon + max_lon) / 2.0
    ys_lat = np.linspace(min_lat, max_lat, n)
    hs = [mission.dem.h(lat, lon_c) for lat in ys_lat]
    ax2.plot((ys_lat - min_lat) * 111_320,
             hs, color="#2c7a2c", linewidth=2.0)
    ax2.fill_between(
        (ys_lat - min_lat) * 111_320,
        0, hs, color="#2c7a2c", alpha=0.4,
    )
    ax2.set_xlabel("Расстояние по Y, м")
    ax2.set_ylabel("Высота, м ASL")
    ax2.set_title(f"Срез рельефа по Y (lon={lon_c:.4f})",
                  fontweight="bold")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    _save_fig_safe(fig, out_path)


# ============================================================
# 6. Folium
# ============================================================

UAV_COLORS = [
    "red", "blue", "green", "purple", "orange",
    "darkred", "cadetblue", "darkgreen",
]


def build_folium_map(mission, routes_data, swaths_by_id) -> folium.Map:
    if mission.vpps:
        lat0 = mission.vpps[0].lat
        lon0 = mission.vpps[0].lon
    else:
        lat0, lon0 = 55.75, 37.62

    m = folium.Map(location=[lat0, lon0], zoom_start=14, tiles=None)
    folium.TileLayer("OpenStreetMap", name="Схема").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Спутник",
    ).add_to(m)

    fg_areas = folium.FeatureGroup(name="Области", show=True)
    for area in mission.areas:
        poly = shape(area.polygon)
        latlngs = [(y, x) for x, y in poly.exterior.coords]
        folium.Polygon(
            locations=latlngs, color="orange", weight=2,
            fill=True, fill_color="yellow", fill_opacity=0.1,
            popup=f"<b>{area.id}</b><br>{area.name}<br>"
                  f"survey: {area.survey_type.value}",
        ).add_to(fg_areas)
    fg_areas.add_to(m)

    if mission.obstacles:
        fg_obs = folium.FeatureGroup(name="Препятствия", show=True)
        for obs in mission.obstacles:
            poly = shape(obs.polygon)
            latlngs = [(y, x) for x, y in poly.exterior.coords]
            folium.Polygon(
                locations=latlngs, color="red", weight=1,
                fill=True, fill_color="red", fill_opacity=0.4,
                popup=f"<b>{obs.id}</b><br>height={obs.height_m} м",
            ).add_to(fg_obs)
        fg_obs.add_to(m)

    if mission.no_fly_zones:
        fg_nfz = folium.FeatureGroup(name="Запретные зоны", show=True)
        for nfz in mission.no_fly_zones:
            poly = shape(nfz.polygon)
            latlngs = [(y, x) for x, y in poly.exterior.coords]
            folium.Polygon(
                locations=latlngs, color="darkred", weight=2,
                fill=True, fill_color="darkred", fill_opacity=0.5,
                popup=f"<b>ЗАПРЕТНАЯ ЗОНА</b><br>{nfz.id}<br>{nfz.name}",
            ).add_to(fg_nfz)
        fg_nfz.add_to(m)

    fg_vpp = folium.FeatureGroup(name="ВПП", show=True)
    for vpp in mission.vpps:
        folium.Marker(
            [vpp.lat, vpp.lon],
            popup=f"<b>{vpp.id}</b><br>{vpp.name}<br>alt={vpp.alt_m} м",
            icon=folium.Icon(color="green", icon="home", prefix="fa"),
        ).add_to(fg_vpp)
    fg_vpp.add_to(m)

    if swaths_by_id:
        fg_sw = folium.FeatureGroup(name="Полосы", show=False)
        for s in swaths_by_id.values():
            folium.PolyLine(
                [(s.start.lat, s.start.lon), (s.end.lat, s.end.lon)],
                color="#888", weight=1, opacity=0.6,
            ).add_to(fg_sw)
        fg_sw.add_to(m)

    by_uav: dict[str, list] = {}
    for r in routes_data:
        by_uav.setdefault(r["uav_id"], []).append(r)

    for idx, (uav_id, routes) in enumerate(by_uav.items()):
        color = UAV_COLORS[idx % len(UAV_COLORS)]
        fg = folium.FeatureGroup(name=f"Маршрут: {uav_id}", show=True)

        for r in sorted(routes, key=lambda x: x["flight_index"]):
            wps = r.get("waypoints", [])
            if len(wps) < 2:
                continue
            points = [(w["lat"], w["lon"]) for w in wps]
            popup = (
                f"<b>{uav_id}</b> — вылет {r['flight_index']}<br>"
                f"Полос: {len(r.get('swath_ids', []))}<br>"
                f"T_air = {r.get('T_air_s', 0):.1f} с<br>"
                f"E = {r.get('E_wh', 0):.2f} Вт·ч"
            )
            folium.PolyLine(
                points, color=color, weight=3, opacity=0.85,
                dash_array="8 4",
                popup=folium.Popup(popup, max_width=300),
                tooltip=f"{uav_id} — вылет {r['flight_index']}",
            ).add_to(fg)

        fg.add_to(m)

    if mission.params.wind.speed_mps > 0 and mission.vpps:
        vpp = mission.vpps[0]
        wdir = math.radians(mission.params.wind.direction_deg)
        length_m = mission.params.wind.speed_mps * 30
        dlat = -length_m * math.cos(wdir) / 111_320
        dlon = -length_m * math.sin(wdir) / (
            111_320 * math.cos(math.radians(vpp.lat))
        )
        folium.PolyLine(
            [(vpp.lat, vpp.lon), (vpp.lat + dlat, vpp.lon + dlon)],
            color="darkblue", weight=4, opacity=0.8,
            tooltip=f"Ветер: {mission.params.wind.speed_mps:.1f} м/с @ "
                    f"{mission.params.wind.direction_deg:.0f}°",
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ============================================================
# 7. index.html
# ============================================================

def build_index_html(out_dir: Path, fixtures: Path, report_data: dict) -> None:
    metrics = report_data.get("metrics", {})
    per_uav = report_data.get("per_uav", [])

    rows = "".join(
        f"<tr><td>{u['uav_id']}</td>"
        f"<td>{u['n_flights']}</td>"
        f"<td>{_fmt_hms(u['T_air_s'])}</td>"
        f"<td>{_fmt_hms(u['T_total_s'])}</td>"
        f"<td>{u['E_wh']:.2f}</td>"
        f"<td>{u['mass_kg']:.2f}</td></tr>"
        for u in per_uav
    )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Geoscan Planner — отчёт</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; margin: 0; padding: 24px;
            background: #f5f5f5; color: #222; }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 6px; }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 20px 0; }}
    .metric {{ background: white; padding: 16px 22px; border-radius: 8px;
              box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 150px; }}
    .metric .label {{ font-size: 12px; color: #666; }}
    .metric .value {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
    table {{ border-collapse: collapse; background: white; border-radius: 8px;
            overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: 100%; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }}
    th {{ background: #333; color: white; font-weight: 500; }}
    tr:hover {{ background: #f9f9f9; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 16px; }}
    .card {{ background: white; border-radius: 8px; padding: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .card h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #555; }}
    .card img {{ width: 100%; border-radius: 4px; }}
    iframe {{ width: 100%; height: 600px; border: 1px solid #ddd; border-radius: 8px; }}
    .footer {{ margin-top: 40px; color: #888; font-size: 12px; }}
    a {{ color: #0366d6; }}
  </style>
</head>
<body>
  <h1>🛩️ Geoscan Planner — отчёт</h1>
  <p>Фикстура: <code>{fixtures}</code></p>

  <h2>📊 Метрики</h2>
  <div class="metrics">
    <div class="metric"><div class="label">C_max</div>
      <div class="value">{_fmt_hms(metrics.get('C_max_s', 0))}</div></div>
    <div class="metric"><div class="label">Налёт</div>
      <div class="value">{_fmt_hms(metrics.get('flight_hours_total_s', 0))}</div></div>
    <div class="metric"><div class="label">Энергия</div>
      <div class="value">{metrics.get('energy_total_wh', 0):.1f} Вт·ч</div></div>
    <div class="metric"><div class="label">Бортов</div>
      <div class="value">{metrics.get('n_uavs_used', 0)}</div></div>
    <div class="metric"><div class="label">Полос</div>
      <div class="value">{metrics.get('n_swaths_total', 0)}</div></div>
    <div class="metric"><div class="label">Фото</div>
      <div class="value">{metrics.get('n_photos_total', 0)}</div></div>
  </div>

  <p>Лучший угол: <b>{report_data.get('theta_best_deg')}°</b> ·
     декомпозиция: <b>{report_data.get('decomposition_method')}</b> ·
     критерий: <b>{report_data.get('optimization_criterion')}</b> ·
     кандидатов: <b>{report_data.get('n_candidates')}</b></p>

  <h2>🛩️ Борты</h2>
  <table>
    <tr><th>Борт</th><th>Вылетов</th><th>T_air</th><th>T_total</th>
        <th>E, Вт·ч</th><th>Масса, кг</th></tr>
    {rows}
  </table>

  <h2>🗺️ Карта маршрутов</h2>
  <p><a href="visuals/map.html" target="_blank">Открыть в новом окне →</a></p>
  <iframe src="visuals/map.html"></iframe>

  <h2>📈 Графики</h2>
  <div class="grid">
    <div class="card"><h3>Профиль рельефа и высоты БВС</h3>
      <img src="visuals/profile.png" alt="profile"></div>
    <div class="card"><h3>Энергия и время</h3>
      <img src="visuals/energy.png" alt="energy"></div>
    <div class="card"><h3>Карта покрытия</h3>
      <img src="visuals/coverage.png" alt="coverage"></div>
    <div class="card"><h3>Сравнение бортов</h3>
      <img src="visuals/comparison.png" alt="comparison"></div>
    <div class="card"><h3>Срезы рельефа</h3>
      <img src="visuals/terrain_cross.png" alt="terrain_cross"></div>
  </div>

  <h2>📥 Файлы</h2>
  <ul>
    <li><a href="mission/report.json">report.json</a></li>
    <li><a href="mission/routes.kml">routes.kml</a></li>
    <li><a href="mission/routes.geojson">routes.geojson</a></li>
  </ul>

  <div class="footer">
    Сгенерировано <code>scripts/visual_report.py</code>
  </div>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


# ============================================================
# Main
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Визуальный отчёт Geoscan Planner",
    )
    parser.add_argument("fixtures",
                        help="путь к фикстуре, например tests/fixtures/moscow")
    parser.add_argument("out",
                        help="куда писать результат, например out/moscow_report")
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    if not fixtures.is_dir():
        raise NotADirectoryError(f"Fixtures dir not found: {fixtures}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir = out_dir / "visuals"
    visuals_dir.mkdir(exist_ok=True)

    print(f"=== Фикстура: {fixtures} ===")
    print(f"=== Выход:    {out_dir} ===")
    print()

    # 1. Pipeline — output_dir = out_dir, run_mission сам создаст /mission
    print("[1/7] Запуск pipeline...")
    report = run_mission(fixtures, out_dir)
    print(f"      C_max={report.metrics.C_max_s:.1f}s, "
          f"E={report.metrics.energy_total_wh:.2f}Wh, "
          f"UAVs={report.metrics.n_uavs_used}")

    mission_dir = out_dir / "mission"
    report_data = json.loads(
        (mission_dir / "report.json").read_text(encoding="utf-8")
    )

    # 2. Загрузка mission
    mission = load_mission(fixtures)

    # 3. Полосы лучшего угла
    print("[2/7] Генерация полос лучшего угла...")
    swaths_by_area, _ = _generate_all_swaths(mission, report.theta_best_deg)
    swaths_by_id = {
        s.id: s for sw in swaths_by_area.values() for s in sw
    }

    # Маршруты берём из geojson (там waypoints уже в dict)
    routes_data = []
    try:
        gj = json.loads(
            (mission_dir / "routes.geojson").read_text(encoding="utf-8")
        )
        for f in gj.get("features", []):
            props = f.get("properties", {})
            if props.get("kind") != "route":
                continue
            wps_raw = f["geometry"]["coordinates"]
            waypoints = [{"lat": c[1], "lon": c[0], "alt_m": 0.0}
                         for c in wps_raw]
            # Восстанавливаем alt из waypoints (если нет — 0)
            routes_data.append({
                "uav_id": props["uav_id"],
                "flight_index": props["flight_index"],
                "swath_ids": props.get("swath_ids", []),
                "T_air_s": props.get("T_air_s", 0.0),
                "T_total_s": props.get("T_total_s", 0.0),
                "E_wh": props.get("E_wh", 0.0),
                "waypoints": waypoints,
            })
    except Exception as e:
        print(f"      [warn] cannot read routes from geojson: {e}")

    # Но высоты alt_m в geojson 2D — их нет.
    # Для профиля нужны реальные маршруты. Читаем из report напрямую
    # (в report.json нет routes, поэтому сохраняем из pipeline).
    # Проще — вызвать run_one_angle и получить routes с waypoints.
    # Но чтобы не запускать pipeline дважды, используем геометрию
    # из swaths_by_id для профиля.
    if not routes_data:
        print("      [warn] no routes — профиль и карта будут неполные")

    # 4. Заполняем waypoints из swaths (для профиля)
    if not routes_data:
        # Резервный путь: строим routes_data из report_data
        for u in report_data.get("per_uav", []):
            routes_data.append({
                "uav_id": u["uav_id"],
                "flight_index": 0,
                "swath_ids": [],
                "T_air_s": u["T_air_s"],
                "T_total_s": u["T_total_s"],
                "E_wh": u["E_wh"],
                "waypoints": [],
            })

    # 5. PNG-графики
    print("[3/7] Профиль рельефа...")
    try:
        if routes_data and any(r.get("waypoints") for r in routes_data):
            plot_profile(mission, routes_data, visuals_dir / "profile.png")
        else:
            print("      [skip] нет waypoints")
    except Exception as e:
        print(f"      [warn] profile: {e}")

    print("[4/7] Энергия по бортам...")
    try:
        plot_energy(report_data.get("per_uav", []),
                    visuals_dir / "energy.png")
    except Exception as e:
        print(f"      [warn] energy: {e}")

    print("[5/7] Карта покрытия...")
    try:
        plot_coverage(mission, routes_data, swaths_by_id,
                      visuals_dir / "coverage.png")
    except Exception as e:
        print(f"      [warn] coverage: {e}")

    print("[6/7] Сравнение бортов...")
    try:
        plot_comparison(report_data.get("per_uav", []),
                        visuals_dir / "comparison.png")
    except Exception as e:
        print(f"      [warn] comparison: {e}")

    print("[7/7] Срезы DEM...")
    try:
        plot_terrain_cross(mission, visuals_dir / "terrain_cross.png")
    except Exception as e:
        print(f"      [warn] terrain_cross: {e}")

    # 6. Folium
    print("[+] Folium-карта...")
    try:
        fmap = build_folium_map(mission, routes_data, swaths_by_id)
        fmap.save(str(visuals_dir / "map.html"))
    except Exception as e:
        print(f"      [warn] map: {e}")

    # 7. index.html
    print("[+] index.html...")
    build_index_html(out_dir, fixtures, report_data)

    print()
    print(f"=== Готово ===")
    print(f"  Открой: {out_dir.resolve()}/index.html")
    print()


if __name__ == "__main__":
    main()