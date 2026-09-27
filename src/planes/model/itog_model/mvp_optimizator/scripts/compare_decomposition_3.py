"""Сравнение трёх методов декомпозиции: trapezoid vs triangulation vs F2C.

Только геометрия полос — без routing, OR-Tools и физики. Быстрый прогон.

ВАЖНО про F2C: Fields2Cover сам оптимизирует направление полос
(минимум числа полос / длины). Поэтому ему НЕ передаётся angle_deg —
он выбирает направление сам. Сравнение с trapezoid/triangulation под
фиксированным углом некорректно «в лоб»: F2C показывает лучший результат
по определению. В CSV для F2C поле angle = "auto".

Выводит:
  - консольную сводку (фигура × угол × метод)
  - CSV: out/compare_3/comparison.csv
  - PNG-сетку (для одного угла): out/compare_3/grid.png

Запуск:
    python3 scripts/compare_decomposition_3.py
"""

from __future__ import annotations

import csv
from io import BytesIO
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.affinity import rotate
from shapely.geometry import Polygon

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition
from planner.geometry.f2c_backend import (
    generate_swaths_f2c,
    is_available as f2c_available,
    get_import_error,
)


OUT_DIR = Path("out/compare_3")
SPACING_M = 20.0
MIN_LEN_M = 3.0
ANGLES = [0.0, 45.0]
PLOT_ANGLE = 0.0


# ============================================================
# Фигуры
# ============================================================

def _circle(cx, cy, r, n=32):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return Polygon([(cx + r * np.cos(t), cy + r * np.sin(t)) for t in a])


def _square(cx, cy, size):
    h = size / 2
    return Polygon([(cx-h, cy-h), (cx+h, cy-h),
                    (cx+h, cy+h), (cx-h, cy+h)])


def _star(cx, cy, r_out, r_in, n=5):
    a = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    pts = [
        (cx + (r_out if i % 2 == 0 else r_in) * np.cos(t),
         cy + (r_out if i % 2 == 0 else r_in) * np.sin(t))
        for i, t in enumerate(a)
    ]
    return Polygon(pts)


def _lshape(cx, cy, size):
    h = size / 2
    return Polygon([
        (cx-h, cy-h), (cx+h, cy-h), (cx+h, cy),
        (cx, cy), (cx, cy+h), (cx-h, cy+h),
    ])


def _shapes():
    return [
        ("circle", _circle(0, 0, 100)),
        ("square", _square(300, 0, 200)),
        ("star", _star(600, 0, 100, 40)),
        ("L-shape", _lshape(900, 0, 200)),
    ]


# ============================================================
# Методы
# ============================================================

def _legacy(method_decompose, poly, angle_deg, spacing):
    """trapezoid / triangulation: поворот полигона + swaths_in_piece."""
    c = poly.centroid
    poly_rot = rotate(poly, -angle_deg, origin=(c.x, c.y))
    pieces = method_decompose(poly_rot)
    lines = []
    for p in pieces:
        lines.extend(swaths_in_piece(p, angle_deg=0.0, spacing_m=spacing))
    lines = [rotate(ln, angle_deg, origin=(c.x, c.y)) for ln in lines]
    return lines, len(pieces)


def swaths_trapezoid(poly, angle_deg, spacing):
    return _legacy(trapezoid_decomposition, poly, angle_deg, spacing)


def swaths_triangulation(poly, angle_deg, spacing):
    return _legacy(triangulation_decomposition, poly, angle_deg, spacing)


def swaths_f2c(poly, angle_deg, spacing):
    """F2C сам оптимизирует направление — angle_deg игнорируется.

    Не поворачиваем полигон: F2C найдёт оптимальное направление сам.
    В отличие от trapezoid/triangulation, которые работают по фиксированному
    углу. Это фича F2C, не баг.
    """
    lines = generate_swaths_f2c(poly, spacing, headland_width_m=0.0)
    return lines, 0


METHODS = {
    "trapezoid": swaths_trapezoid,
    "triangulation": swaths_triangulation,
    "fields2cover": swaths_f2c,
}


# ============================================================
# Плот
# ============================================================

def _save_fig_safe(fig, out_path: Path, dpi: int = 100) -> None:
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    except Exception as e:
        print(f"  [warn] bbox_inches failed: {e}")
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())


def make_grid_plot(results, angle, out_path: Path):
    """Сетка: строки — фигуры, колонки — методы."""
    shape_names = [n for n, _ in _shapes()]
    method_names = list(METHODS.keys())

    fig, axes = plt.subplots(
        len(shape_names), len(method_names),
        figsize=(4 * len(method_names), 5 * len(shape_names)),
        squeeze=False,
    )

    for i, shape_name in enumerate(shape_names):
        for j, method in enumerate(method_names):
            ax = axes[i][j]
            data = results.get((shape_name, method))
            if data is None:
                ax.set_axis_off()
                ax.set_title(
                    f"{shape_name} / {method}\n(n/a)",
                    fontsize=10,
                )
                continue

            for line in data["lines"]:
                xs, ys = line.xy
                ax.plot(xs, ys, "k-", linewidth=2.0,
                        solid_capstyle="round")

            poly = data["poly"]
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, "b-", linewidth=0.8, alpha=0.5)

            ax.set_aspect("equal")
            ax.axis("off")
            n = len(data["lines"])
            title = f"{shape_name} / {method}\n{n} swaths"
            if method == "fields2cover":
                title += " (auto dir)"
            ax.set_title(title, fontsize=10, fontweight="bold")

    fig.suptitle(
        f"Сравнение методов декомпозиции — угол {angle:.0f}° "
        f"(F2C сам выбирает направление)",
        fontsize=16, fontweight="bold", y=0.995,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.98])
    _save_fig_safe(fig, out_path, dpi=100)
    plt.close(fig)
    print(f"  grid → {out_path}")


# ============================================================
# Main
# ============================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    methods = ["trapezoid", "triangulation"]
    if f2c_available():
        methods.append("fields2cover")
        print("F2C available — added to comparison.")
    else:
        print(f"F2C NOT available: {get_import_error()}")
        print("Skipping fields2cover.")

    rows = []
    plot_results = {}

    for angle in ANGLES:
        print(f"\n=== angle {angle}° ===")
        for name, poly in _shapes():
            print(f"  [{name}]  area={poly.area:.0f} m²")
            for method in methods:
                fn = METHODS[method]
                try:
                    lines, n_pieces = fn(poly, angle, SPACING_M)
                    lines = [ln for ln in lines if ln.length >= MIN_LEN_M]
                    total_len = sum(ln.length for ln in lines)
                    print(f"    {method:14s} → {len(lines):3d} swaths, "
                          f"{total_len:8.0f} m, pieces={n_pieces}")
                    rows.append({
                        "angle": "auto" if method == "fields2cover" else angle,
                        "shape": name,
                        "method": method,
                        "n_swaths": len(lines),
                        "total_length_m": round(total_len, 1),
                        "n_pieces": n_pieces,
                        "error": "",
                    })
                    if angle == PLOT_ANGLE:
                        plot_results[(name, method)] = {
                            "lines": lines, "poly": poly,
                        }
                except Exception as e:
                    print(f"    {method:14s} → FAIL: {e}")
                    rows.append({
                        "angle": "auto" if method == "fields2cover" else angle,
                        "shape": name, "method": method,
                        "n_swaths": -1, "total_length_m": 0.0, "n_pieces": -1,
                        "error": str(e),
                    })

    csv_path = OUT_DIR / "comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["angle", "shape", "method",
                        "n_swaths", "total_length_m", "n_pieces", "error"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV → {csv_path}")

    if plot_results:
        make_grid_plot(plot_results, PLOT_ANGLE, OUT_DIR / "grid.png")

    print("\nГотово. Файлы в", OUT_DIR.resolve())


if __name__ == "__main__":
    main()