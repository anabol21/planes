"""Сравнение trapezoid vs triangulation на 5 фигурах × N углов.

Генерирует:
    out/compare/plot_methods_a{angle}.png
    out/compare/map_trapezoid_a{angle}.html
    out/compare/map_triangulation_a{angle}.html
    out/compare/compare_a{angle}.html
    out/compare/comparison.csv

Запуск:
    python3 scripts/visualize_methods.py
"""

from __future__ import annotations

import csv
from io import BytesIO
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium
from shapely.geometry import Polygon
from shapely.ops import transform

from planner.geometry.merge import merge_thin_pieces
from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.models import (
    Area, Obstacle, Params, Wind, Criterion, DecompositionMethod,
    MissionInput, VPP, UAVConfig, SurveyType, Route,
)
from planner.utils.geo import make_local_transformer
from planner.io.catalog import get_default_catalog
from planner.physics import build_physics_model, build_physics_params
from planner.solver.multi_flight import solve_multi_flight


OUT_DIR = Path("out/compare")


# ============================================================
# НАСТРОЙКИ
# ============================================================

ANGLES_DEG = [0.0, 45.0, 90.0, 135.0]
SPACING_M = 20.0
MIN_SWATH_LEN_M = 3.0
MERGE_THIN = True
MAPS_FOR_ALL_ANGLES = False


# ============================================================
# Фигуры
# ============================================================

def _make_circle(cx, cy, r, n=32):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return Polygon([(cx + r * np.cos(a), cy + r * np.sin(a)) for a in angles])


def _make_square(cx, cy, size):
    h = size / 2
    return Polygon([
        (cx - h, cy - h), (cx + h, cy - h),
        (cx + h, cy + h), (cx - h, cy + h),
    ])


def _make_star(cx, cy, r_out, r_in, n=5):
    angles = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    pts = []
    for i, a in enumerate(angles):
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    return Polygon(pts)


def _make_triangle(cx, cy, r):
    angles = [np.pi / 2, np.pi / 2 + 2 * np.pi / 3, np.pi / 2 + 4 * np.pi / 3]
    return Polygon([(cx + r * np.cos(a), cy + r * np.sin(a)) for a in angles])


def _make_lshape(cx, cy, size):
    h = size / 2
    return Polygon([
        (cx - h, cy - h), (cx + h, cy - h),
        (cx + h, cy), (cx, cy),
        (cx, cy + h), (cx - h, cy + h),
    ])


def _shape_specs():
    return [
        ("circle", _make_circle(0, 0, 100, 32), _make_square(0, 0, 40)),
        ("square", _make_square(300, 0, 200), _make_square(320, 20, 50)),
        ("star", _make_star(600, 0, 100, 40, 5), _make_square(600, 0, 30)),
        ("triangle", _make_triangle(900, 0, 100), _make_square(880, -20, 30)),
        ("L-shape", _make_lshape(1200, 0, 200), _make_square(1230, -30, 40)),
    ]


# ============================================================
# Декомпозиция
# ============================================================

def decompose_shape(polygon_m: Polygon, method: str) -> list:
    if method == "triangulation":
        return triangulation_decomposition(polygon_m)
    return trapezoid_decomposition(polygon_m)


def _filter_swaths(swaths, min_len_m: float):
    return [s for s in swaths if s.length >= min_len_m]


def swaths_for_shape(
    polygon_m: Polygon,
    method: str,
    spacing_m: float = 20.0,
    obstacle_m: Polygon | None = None,
    angle_deg: float = 0.0,
    merge_thin: bool = True,
    min_swath_len_m: float = 3.0,
):
    if obstacle_m is not None and not obstacle_m.is_empty:
        polygon_m = polygon_m.difference(obstacle_m)

    pieces = decompose_shape(polygon_m, method)

    if merge_thin:
        pieces = merge_thin_pieces(pieces, min_width_m=spacing_m * 0.75)

    swaths = []
    for p in pieces:
        swaths.extend(
            swaths_in_piece(p, angle_deg=angle_deg, spacing_m=spacing_m)
        )

    swaths = _filter_swaths(swaths, min_swath_len_m)
    return pieces, swaths


# ============================================================
# Matplotlib
# ============================================================

def _save_fig_safe(fig, out_path: Path, dpi: int = 100) -> None:
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    except Exception as e:
        print(f"  [warn] bbox_inches failed: {e}. Retry without.")
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())


def make_plot_for_angle(results: dict, angle_deg: float, out_path: Path):
    shape_names = ["circle", "square", "star", "triangle", "L-shape"]
    methods = ["trapezoid", "triangulation"]

    fig, axes = plt.subplots(
        len(shape_names), len(methods),
        figsize=(14, 26),
        squeeze=False,
    )

    cmap_pieces = plt.cm.tab20

    for i, shape_name in enumerate(shape_names):
        for j, method in enumerate(methods):
            ax = axes[i][j]
            data = results[(shape_name, method)]

            for k, p in enumerate(data["pieces"]):
                if p.is_empty:
                    continue
                geoms = [p] if p.geom_type == "Polygon" else list(p.geoms)
                for geom in geoms:
                    xs, ys = geom.exterior.xy
                    ax.fill(
                        xs, ys, alpha=0.35,
                        color=cmap_pieces(k % 20),
                        edgecolor="black", linewidth=0.5,
                    )
                    for interior in geom.interiors:
                        hx, hy = interior.xy
                        ax.fill(hx, hy, color="white",
                                edgecolor="black", linewidth=0.5)

            if data["obstacle"] is not None:
                oxs, oys = data["obstacle"].exterior.xy
                ax.fill(oxs, oys, color="red", alpha=0.55,
                        edgecolor="darkred", linewidth=1.0)

            for s in data["swaths"]:
                xs, ys = s.xy
                ax.plot(xs, ys, "k-", linewidth=2.0, solid_capstyle="round")

            ax.set_aspect("equal")
            ax.axis("off")

            n_sw = len(data["swaths"])
            n_pc = len(data["pieces"])
            title = f"{shape_name} / {method}\n{n_pc} pieces, {n_sw} swaths"
            ax.set_title(title, fontsize=11, fontweight="bold")

    fig.suptitle(
        f"Угол полос: {angle_deg:.0f}°",
        fontsize=18, fontweight="bold", y=0.995,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    _save_fig_safe(fig, out_path, dpi=100)
    plt.close(fig)
    print(f"  plot (angle={angle_deg}°) → {out_path}")


# ============================================================
# Folium
# ============================================================

def _polygon_to_geojson(poly_wgs: Polygon) -> dict:
    coords = [[pt[0], pt[1]] for pt in poly_wgs.exterior.coords]
    holes = []
    for interior in poly_wgs.interiors:
        holes.append([[pt[0], pt[1]] for pt in interior.coords])
    if holes:
        return {"type": "Polygon", "coordinates": [coords] + holes}
    return {"type": "Polygon", "coordinates": [coords]}


def run_one_shape_pipeline(
    shape_name: str,
    polygon_wgs: Polygon,
    obstacle_wgs: Polygon | None,
    method: str,
    vpp: VPP,
    uav: UAVConfig,
    catalog,
    angle_deg: float = 0.0,
):
    area = Area(
        id=f"area-{shape_name}",
        name=shape_name,
        survey_type=SurveyType.VISIBLE,
        polygon=_polygon_to_geojson(polygon_wgs),
    )

    obstacles = []
    if obstacle_wgs is not None and not obstacle_wgs.is_empty:
        obstacles.append(Obstacle(
            id=f"obs-{shape_name}",
            name=f"obs-{shape_name}",
            height_m=30.0,
            polygon=_polygon_to_geojson(obstacle_wgs),
        ))

    params = Params(
        gsd_cm_per_px=3.0,
        wind=Wind(speed_mps=7.0, direction_deg=90.0),
        angles_deg=[angle_deg],
        optimization_criterion=Criterion.MIN_TIME,
        attempts_max=1,
        R_max=3,
        decomposition=DecompositionMethod(method),
    )

    from planner.geometry.generate import generate_swaths_for_area
    cam = catalog.get_camera(uav.camera_id)

    pp = build_physics_params(uav, catalog, reserve_fraction=params.reserve_fraction)
    model = build_physics_model(pp)
    P_nominal = model.power_w(pp.v_air_mps, params.wind.speed_mps)

    swaths, h_agl = generate_swaths_for_area(
        area=area,
        obstacles=obstacles,
        angle_deg=angle_deg,
        gsd_cm_per_px=params.gsd_cm_per_px,
        camera=cam,
        decomposition=method,
        v_climb_mps=pp.v_climb_mps,
        v_descent_mps=pp.v_descent_mps,
        v_min_mps=pp.v_min_mps,
        v_survey_mps=pp.v_survey_mps,
        mass_kg=pp.mass_kg,
        P_nominal_w=P_nominal,
    )

    if not swaths:
        return None, [], None, []

    fwd, inv = make_local_transformer(vpp.lon, vpp.lat)

    # Оbstacles в ENU
    from planner.solver.obstacles import prepare_obstacles_m
    obs_geojsons = [o.polygon for o in obstacles]
    obstacles_m = prepare_obstacles_m(obs_geojsons, fwd)

    results = solve_multi_flight(
        uav_id=uav.id,
        swaths=swaths,
        vpp=vpp,
        fwd=fwd,
        physics=model,
        params=pp,
        wind_speed_mps=params.wind.speed_mps,
        wind_direction_deg=params.wind.direction_deg,
        h_agl_m=h_agl,
        R_max=params.R_max,
        obstacles_m=obstacles_m,
    )

    # Waypoints
    from planner.solver.pipeline import _compute_route_waypoints
    swaths_by_id = {s.id: s for s in swaths}

    routes = []
    for i, r in enumerate(results):
        wps = _compute_route_waypoints(
            swath_ids=r.swath_ids,
            swaths_by_id=swaths_by_id,
            vpp=vpp,
            fwd=fwd,
            inv=inv,
            obstacles_m=obstacles_m,
        )
        routes.append(Route(
            uav_id=uav.id, flight_index=i, vpp_id=r.vpp_id,
            swath_ids=r.swath_ids, T_air_s=r.T_air_s,
            T_total_s=r.T_total_s, E_wh=r.E_wh, mass_kg=pp.mass_kg,
            waypoints=wps,
        ))

    return routes, swaths, h_agl, obstacles_m


def make_folium_map(
    all_results: dict,
    method: str,
    vpp: VPP,
    out_path: Path,
    angle_deg: float,
):
    m = folium.Map(location=[vpp.lat, vpp.lon], zoom_start=16, tiles=None)
    folium.TileLayer("OpenStreetMap", name="Схема").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Спутник",
    ).add_to(m)

    all_latlngs = []

    for shape_name, data in all_results[method].items():
        coords = data["polygon_wgs"]["coordinates"][0]
        latlngs = [(pt[1], pt[0]) for pt in coords]
        all_latlngs.extend(latlngs)

        has_swaths = bool(data["swaths"])
        folium.Polygon(
            locations=latlngs,
            color="orange" if has_swaths else "gray",
            weight=2, fill=True,
            fill_color="yellow" if has_swaths else "lightgray",
            fill_opacity=0.10,
            tooltip=f"{shape_name} ({len(data['swaths'])} swaths)",
        ).add_to(m)

        for obs_geo in data.get("obstacles_wgs", []):
            occ = obs_geo["coordinates"][0]
            occ_ll = [(pt[1], pt[0]) for pt in occ]
            folium.Polygon(
                locations=occ_ll,
                color="red", weight=1, fill=True,
                fill_color="red", fill_opacity=0.5,
            ).add_to(m)

        if not has_swaths:
            continue

        for s in data["swaths"]:
            latlngs = [(s.start.lat, s.start.lon), (s.end.lat, s.end.lon)]
            all_latlngs.extend(latlngs)
            folium.PolyLine(
                locations=latlngs,
                color="#222", weight=2, opacity=0.8,
                tooltip=s.id,
            ).add_to(m)

        for r in data["routes"]:
            # NEW: waypoints если есть
            if getattr(r, "waypoints", None):
                points = [(p.lat, p.lon) for p in r.waypoints]
            else:
                points = [(vpp.lat, vpp.lon)]
                for sid in r.swath_ids:
                    sw = data["swaths_by_id"].get(sid)
                    if not sw:
                        continue
                    points.append((sw.start.lat, sw.start.lon))
                    points.append((sw.end.lat, sw.end.lon))
                points.append((vpp.lat, vpp.lon))

            folium.PolyLine(
                locations=points, color="blue",
                weight=3, opacity=0.7, dash_array="6 3",
                tooltip=f"{shape_name}: {len(r.swath_ids)} swaths, "
                        f"T={r.T_total_s:.0f}s",
            ).add_to(m)

    folium.Marker(
        location=[vpp.lat, vpp.lon],
        icon=folium.Icon(color="green", icon="home", prefix="fa"),
        popup=f"VPP: {vpp.id}",
    ).add_to(m)

    if all_latlngs:
        m.fit_bounds(all_latlngs, padding=[30, 30])

    folium.LayerControl(collapsed=False).add_to(m)

    title_html = f"""
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                background: white; padding: 8px 20px; border-radius: 6px;
                font-family: sans-serif; font-size: 16px; font-weight: bold;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3); z-index: 9999;">
      {method} — угол {angle_deg:.0f}°
    </div>"""
    m.get_root().html.add_child(folium.Element(title_html))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"  map ({method}, angle={angle_deg}°) → {out_path}")


def make_compare_html(trap_path: Path, tri_path: Path, out_path: Path, angle_deg: float):
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Comparison: trapezoid vs triangulation (angle={angle_deg}°)</title>
  <style>
    body {{ margin: 0; font-family: sans-serif; background: #222; color: white; }}
    h1 {{ text-align: center; padding: 10px; margin: 0; font-size: 20px; }}
    .container {{ display: flex; width: 100vw; height: calc(100vh - 50px); }}
    .pane {{ flex: 1; display: flex; flex-direction: column; }}
    .pane h2 {{ text-align: center; margin: 5px; font-size: 16px; }}
    iframe {{ flex: 1; border: none; }}
  </style>
</head>
<body>
  <h1>Сравнение декомпозиции: trapezoid vs triangulation — угол {angle_deg:.0f}°</h1>
  <div class="container">
    <div class="pane">
      <h2>TRAPEZOID</h2>
      <iframe src="{trap_path.name}"></iframe>
    </div>
    <div class="pane">
      <h2>TRIANGULATION</h2>
      <iframe src="{tri_path.name}"></iframe>
    </div>
  </div>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  compare (angle={angle_deg}°) → {out_path}")


# ============================================================
# Main
# ============================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Angles: {ANGLES_DEG}")
    print(f"Spacing: {SPACING_M} m, merge_thin: {MERGE_THIN}")
    print()

    shapes = _shape_specs()

    base_lat, base_lon = 55.7505, 37.620
    fwd, inv = make_local_transformer(base_lon, base_lat)

    vpp_lon, vpp_lat = inv.transform(600, -250)
    vpp = VPP(id="vpp-1", name="Main VPP", lat=vpp_lat, lon=vpp_lon, alt_m=150)

    uav = UAVConfig(
        id="gemini-1", model="gemini", camera_id="pf1b",
        battery_id="battery-gemini", vpp_id="vpp-1",
    )
    catalog = get_default_catalog()

    csv_rows = []
    generated_maps_for = None

    for angle in ANGLES_DEG:
        print(f"=== Angle {angle}° ===")

        plot_results = {}

        for shape_name, poly_m, obs_m in shapes:
            for method in ["trapezoid", "triangulation"]:
                pieces, swaths = swaths_for_shape(
                    poly_m, method,
                    spacing_m=SPACING_M,
                    obstacle_m=obs_m,
                    angle_deg=angle,
                    merge_thin=MERGE_THIN,
                    min_swath_len_m=MIN_SWATH_LEN_M,
                )

                plot_results[(shape_name, method)] = {
                    "polygon": poly_m,
                    "obstacle": obs_m,
                    "pieces": pieces,
                    "swaths": swaths,
                }

                total_len = sum(s.length for s in swaths)
                csv_rows.append({
                    "angle": angle,
                    "shape": shape_name,
                    "method": method,
                    "n_pieces": len(pieces),
                    "n_swaths": len(swaths),
                    "total_length_m": round(total_len, 1),
                })

        png_name = f"plot_methods_a{int(angle)}.png"
        make_plot_for_angle(plot_results, angle, OUT_DIR / png_name)

        do_maps = MAPS_FOR_ALL_ANGLES or generated_maps_for is None
        if do_maps:
            print(f"  Running pipelines for folium maps (angle={angle})...")
            map_results = {"trapezoid": {}, "triangulation": {}}

            def _local_to_wgs(x, y):
                lon, lat = inv.transform(x, y)
                return lon, lat

            for shape_name, poly_m, obs_m in shapes:
                poly_wgs = transform(_local_to_wgs, poly_m)
                obs_wgs = transform(_local_to_wgs, obs_m)
                obs_geojson = _polygon_to_geojson(obs_wgs) if obs_wgs else None

                for method in ["trapezoid", "triangulation"]:
                    routes, swaths, h_agl, _ = run_one_shape_pipeline(
                        shape_name=shape_name,
                        polygon_wgs=poly_wgs,
                        obstacle_wgs=obs_wgs,
                        method=method,
                        vpp=vpp,
                        uav=uav,
                        catalog=catalog,
                        angle_deg=angle,
                    )
                    map_results[method][shape_name] = {
                        "polygon_wgs": _polygon_to_geojson(poly_wgs),
                        "obstacles_wgs": [obs_geojson] if obs_geojson else [],
                        "swaths": swaths or [],
                        "swaths_by_id": {s.id: s for s in (swaths or [])},
                        "routes": routes or [],
                    }
                    print(f"    {shape_name}/{method}: "
                          f"{len(swaths or [])} swaths")

            suffix = f"_a{int(angle)}"
            trap_html = OUT_DIR / f"map_trapezoid{suffix}.html"
            tri_html = OUT_DIR / f"map_triangulation{suffix}.html"
            cmp_html = OUT_DIR / f"compare{suffix}.html"

            make_folium_map(map_results, "trapezoid", vpp, trap_html, angle)
            make_folium_map(map_results, "triangulation", vpp, tri_html, angle)
            make_compare_html(trap_html, tri_html, cmp_html, angle)

            generated_maps_for = angle

        print()

    csv_path = OUT_DIR / "comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "angle", "shape", "method",
                "n_pieces", "n_swaths", "total_length_m",
            ],
        )
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"csv → {csv_path}")

    print()
    print(f"Done. Файлы в {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()