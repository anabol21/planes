"""Сравнение трёх методов декомпозиции на СЛОЖНЫХ КРИВЫХ областях.

Фигуры: вогнутая, с дыркой, звезда (8 лучей), спираль, «амёба», L с дыркой.
Методы: trapezoid, triangulation, fields2cover.

Генерирует:
    out/curves/
      map_trapezoid.html
      map_triangulation.html
      map_fields2cover.html     (если F2C доступен)
      compare.html              — side-by-side iframe
      comparison.csv            — метрики (n_swaths, длина)
      shapes_overview.png       — PNG-сетка фигур

Запуск:
    python3 scripts/compare_f2c_curves.py
"""

from __future__ import annotations

import csv
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium
from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.geometry.f2c_backend import (
    generate_swaths_f2c,
    is_available as f2c_available,
    get_import_error,
)
from planner.utils.geo import make_local_transformer


OUT_DIR = Path("out/curves")
SPACING_M = 20.0
MIN_LEN_M = 3.0
ANGLE_DEG = 45.0         # для trapezoid/triangulation
SHAPE_GAP_M = 500.0      # расстояние между фигурами по X
BASE_LAT = 55.7505
BASE_LON = 37.620

METHODS = ["trapezoid", "triangulation", "fields2cover"]


# ============================================================
# Сложные фигуры (в локальных метрах, ENU)
# ============================================================

def _concave(cx, cy, size=200):
    """Вогнутая: с прямоугольной выемкой сверху."""
    h = size / 2
    return Polygon([
        (cx - h, cy - h),
        (cx + h, cy - h),
        (cx + h, cy + h),
        (cx + h * 0.2, cy + h),
        (cx + h * 0.2, cy + h * 0.3),
        (cx - h * 0.2, cy + h * 0.3),
        (cx - h * 0.2, cy + h),
        (cx - h, cy + h),
    ])


def _with_hole(cx, cy, size=220):
    """Прямоугольник с квадратной дыркой посередине."""
    h = size / 2
    outer = Polygon([(cx-h, cy-h), (cx+h, cy-h),
                     (cx+h, cy+h), (cx-h, cy+h)])
    hole = Polygon([(cx-40, cy-40), (cx+40, cy-40),
                    (cx+40, cy+40), (cx-40, cy+40)])
    return outer.difference(hole)


def _star8(cx, cy, r_out=130, r_in=50):
    """8-конечная звезда."""
    pts = []
    for i in range(16):
        t = 2 * math.pi * i / 16
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return Polygon(pts)


def _spiral(cx, cy, turns=2.5, r_max=120, r_min=20, n=200):
    """Спираль — «почти» полигон, вращающийся вокруг центра."""
    pts = []
    for i in range(n + 1):
        t = i / n
        ang = 2 * math.pi * turns * t
        r = r_min + (r_max - r_min) * t
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    # Замыкаем через центр
    pts.append((cx, cy))
    return Polygon(pts).buffer(15, resolution=4)


def _amoeba(cx, cy, n=48, base_r=120):
    """Амёба — многоугольник с синусоидальным радиусом."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = base_r + 40 * math.sin(5 * t) + 25 * math.cos(3 * t)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return Polygon(pts)


def _l_with_hole(cx, cy, size=240):
    """L-образный с дыркой в широкой части."""
    h = size / 2
    outer = Polygon([
        (cx-h, cy-h), (cx+h, cy-h), (cx+h, cy),
        (cx, cy), (cx, cy+h), (cx-h, cy+h),
    ])
    hole = Polygon([(cx-h+20, cy-h+20), (cx+h-60, cy-h+20),
                    (cx+h-60, cy-40), (cx-h+20, cy-40)])
    return outer.difference(hole)


def _shapes():
    """Список фигур с раскладкой по X в локальных метрах."""
    return [
        ("concave",   _concave(0, 0)),
        ("with_hole", _with_hole(SHAPE_GAP_M, 0)),
        ("star8",     _star8(2 * SHAPE_GAP_M, 0)),
        ("spiral",    _spiral(3 * SHAPE_GAP_M, 0)),
        ("amoeba",    _amoeba(4 * SHAPE_GAP_M, 0)),
        ("L_hole",    _l_with_hole(5 * SHAPE_GAP_M, 0)),
    ]


# ============================================================
# Методы
# ============================================================

def _legacy(method_decompose, poly, angle_deg, spacing):
    c = poly.centroid
    poly_rot = rotate(poly, -angle_deg, origin=(c.x, c.y))
    try:
        pieces = method_decompose(poly_rot)
    except Exception as e:
        print(f"      decompose failed: {e}")
        return []
    lines = []
    for p in pieces:
        if p.is_empty:
            continue
        lines.extend(swaths_in_piece(p, angle_deg=0.0, spacing_m=spacing))
    lines = [rotate(ln, angle_deg, origin=(c.x, c.y)) for ln in lines]
    return [ln for ln in lines if ln.length >= MIN_LEN_M]


def run_trapezoid(poly):
    return _legacy(trapezoid_decomposition, poly, ANGLE_DEG, SPACING_M)


def run_triangulation(poly):
    return _legacy(triangulation_decomposition, poly, ANGLE_DEG, SPACING_M)


def run_f2c(poly):
    try:
        lines = generate_swaths_f2c(poly, SPACING_M, headland_width_m=0.0)
        return [ln for ln in lines if ln.length >= MIN_LEN_M]
    except Exception as e:
        print(f"      F2C failed: {e}")
        return []


METHODS_FN = {
    "trapezoid": run_trapezoid,
    "triangulation": run_triangulation,
    "fields2cover": run_f2c,
}


# ============================================================
# Transform ENU → WGS84
# ============================================================

def _setup_transform():
    fwd, inv = make_local_transformer(BASE_LON, BASE_LAT)

    def to_wgs(x, y):
        lon, lat = inv.transform(x, y)
        return lon, lat

    return fwd, inv, to_wgs


def _poly_to_latlng(poly_m, to_wgs):
    """Polygon в метрах → список (lat, lon) для folium."""
    coords = list(poly_m.exterior.coords)
    latlngs = []
    for x, y in coords:
        lon, lat = to_wgs(x, y)
        latlngs.append((lat, lon))
    return latlngs


def _line_to_latlng(line_m, to_wgs):
    (x1, y1), (x2, y2) = line_m.coords[0], line_m.coords[-1]
    lon1, lat1 = to_wgs(x1, y1)
    lon2, lat2 = to_wgs(x2, y2)
    return [(lat1, lon1), (lat2, lon2)]


# ============================================================
# Folium
# ============================================================

def make_map(
    results: dict,
    method: str,
    to_wgs,
    out_path: Path,
) -> None:
    """Одна карта: все фигуры + полосы одного метода."""
    m = folium.Map(
        location=[BASE_LAT, BASE_LON],
        zoom_start=13,
        tiles=None,
    )
    folium.TileLayer("OpenStreetMap", name="Схема").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Спутник",
    ).add_to(m)

    all_latlngs = []

    for shape_name, data in results.items():
        # Полигон фигуры
        latlngs = _poly_to_latlng(data["poly"], to_wgs)
        all_latlngs.extend(latlngs)

        # Дырки
        holes = [
            _poly_to_latlng(Polygon([pt for pt in ring.coords]), to_wgs)
            for ring in data["poly"].interiors
        ]

        folium.Polygon(
            locations=latlngs,
            color="blue", weight=2, fill=True,
            fill_color="lightblue", fill_opacity=0.15,
            tooltip=f"{shape_name} ({data['n_swaths']} swaths)",
        ).add_to(m)

        for h in holes:
            folium.Polygon(
                locations=h,
                color="blue", weight=1, fill=True,
                fill_color="white", fill_opacity=0.6,
            ).add_to(m)

        # Полосы
        for line in data["lines"]:
            seg = _line_to_latlng(line, to_wgs)
            all_latlngs.extend(seg)
            folium.PolyLine(
                locations=seg,
                color="black", weight=2, opacity=0.8,
                tooltip=f"{shape_name}: {line.length:.0f} m",
            ).add_to(m)

    if all_latlngs:
        m.fit_bounds(all_latlngs, padding=[30, 30])

    folium.LayerControl(collapsed=False).add_to(m)

    title_html = f"""
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                background: white; padding: 8px 20px; border-radius: 6px;
                font-family: sans-serif; font-size: 16px; font-weight: bold;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3); z-index: 9999;">
      {method}
    </div>"""
    m.get_root().html.add_child(folium.Element(title_html))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"  map ({method}) → {out_path}")


def make_compare_html(method_paths: dict, out_path: Path) -> None:
    """Side-by-side сравнение методов в iframe."""
    panes = "\n".join(
        f'<div class="pane">'
        f'<h2>{m.upper()}</h2>'
        f'<iframe src="{p.name}"></iframe>'
        f'</div>'
        for m, p in method_paths.items()
    )
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Сравнение методов — кривые области</title>
  <style>
    body {{ margin: 0; font-family: sans-serif; background: #222; color: white; }}
    h1 {{ text-align: center; padding: 10px; margin: 0; font-size: 18px; }}
    .container {{ display: flex; width: 100vw; height: calc(100vh - 50px); }}
    .pane {{ flex: 1; display: flex; flex-direction: column; }}
    .pane h2 {{ text-align: center; margin: 5px; font-size: 16px; }}
    iframe {{ flex: 1; border: none; }}
  </style>
</head>
<body>
  <h1>Кривые области: trapezoid vs triangulation vs fields2cover</h1>
  <div class="container">{panes}</div>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  compare → {out_path}")


# ============================================================
# PNG overview
# ============================================================

def _save_fig_safe(fig, out_path: Path, dpi: int = 100) -> None:
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    except Exception:
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())


def make_png_grid(results_all: dict, out_path: Path) -> None:
    """Сетка: строки — фигуры, колонки — методы."""
    shapes = list(results_all.keys())
    methods = list(METHODS_FN.keys())

    fig, axes = plt.subplots(
        len(shapes), len(methods),
        figsize=(4 * len(methods), 4 * len(shapes)),
        squeeze=False,
    )

    for i, shape in enumerate(shapes):
        for j, method in enumerate(methods):
            ax = axes[i][j]
            data = results_all[shape].get(method)
            if not data:
                ax.set_axis_off()
                ax.set_title(f"{shape} / {method}\n(n/a)", fontsize=9)
                continue

            poly = data["poly"]
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, "b-", linewidth=0.6, alpha=0.4)
            for ring in poly.interiors:
                hx, hy = ring.xy
                ax.plot(hx, hy, "b-", linewidth=0.6, alpha=0.4)

            for ln in data["lines"]:
                lxs, lys = ln.xy
                ax.plot(lxs, lys, "k-", linewidth=1.4)

            ax.set_aspect("equal")
            ax.axis("off")
            n = len(data["lines"])
            total = sum(ln.length for ln in data["lines"])
            ax.set_title(
                f"{shape} / {method}\n{n} swaths, {total:.0f} m",
                fontsize=9, fontweight="bold",
            )

    fig.suptitle(
        "Сложные области: сравнение декомпозиции",
        fontsize=14, fontweight="bold", y=0.995,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.98])
    _save_fig_safe(fig, out_path, dpi=100)
    plt.close(fig)
    print(f"  png grid → {out_path}")


# ============================================================
# Main
# ============================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    methods = ["trapezoid", "triangulation"]
    if f2c_available():
        methods.append("fields2cover")
        print("F2C available.")
    else:
        print(f"F2C NOT available: {get_import_error()}")
        print("Продолжаем без fields2cover.")

    _, _, to_wgs = _setup_transform()

    # results[shape][method] = {"lines": [...], "poly": Polygon, "n_swaths": int}
    results: dict[str, dict[str, dict]] = {}

    print("\n=== Прогон методов ===")
    for shape_name, poly in _shapes():
        results[shape_name] = {}
        print(f"\n[{shape_name}]  area={poly.area:.0f} m²")

        for method in methods:
            fn = METHODS_FN[method]
            try:
                lines = fn(poly)
            except Exception as e:
                print(f"  {method:14s} → FAIL: {e}")
                lines = []

            total_len = sum(ln.length for ln in lines)
            print(f"  {method:14s} → {len(lines):3d} swaths, "
                  f"{total_len:8.0f} m")

            results[shape_name][method] = {
                "lines": lines,
                "poly": poly,
                "n_swaths": len(lines),
                "total_length_m": total_len,
            }

    # --- Folium карты ---
    print("\n=== Folium карты ===")
    method_paths: dict[str, Path] = {}
    for method in methods:
        per_method = {
            shape: results[shape][method]
            for shape in results
            if method in results[shape]
        }
        path = OUT_DIR / f"map_{method}.html"
        make_map(per_method, method, to_wgs, path)
        method_paths[method] = path

    if len(method_paths) >= 2:
        make_compare_html(method_paths, OUT_DIR / "compare.html")

    # --- PNG ---
    make_png_grid(results, OUT_DIR / "shapes_overview.png")

    # --- CSV ---
    csv_path = OUT_DIR / "comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["shape", "method", "n_swaths",
                         "total_length_m", "area_m2"])
        for shape_name, per_method in results.items():
            for method, data in per_method.items():
                writer.writerow([
                    shape_name, method,
                    data["n_swaths"],
                    round(data["total_length_m"], 1),
                    round(data["poly"].area, 1),
                ])
    print(f"  csv → {csv_path}")

    print(f"\nГотово. Открывай {OUT_DIR.resolve()}/compare.html")


if __name__ == "__main__":
    main()