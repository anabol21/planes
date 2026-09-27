"""Диагностика: сколько pieces/swaths при разных углах."""

from __future__ import annotations

import sys

from shapely.geometry import Polygon

from planner.geometry.swath import swaths_in_piece
from planner.geometry.trapezoid import trapezoid_decomposition
from planner.geometry.triangulation import triangulation_decomposition


def diagnose(polygon, spacing_m=126.0, angles=(0, 45, 90)):
    print(f"Polygon bounds: {polygon.bounds}")
    print(f"Spacing: {spacing_m} m")
    print()

    for method_name, decompose in [
        ("trapezoid", trapezoid_decomposition),
        ("triangulation", triangulation_decomposition),
    ]:
        print(f"--- {method_name} ---")
        pieces = decompose(polygon)
        print(f"  pieces: {len(pieces)}")
        for i, p in enumerate(pieces):
            print(f"    piece {i}: area={p.area:.0f}, "
                  f"bounds={tuple(round(x,1) for x in p.bounds)}")

        for angle in angles:
            all_sw = []
            for p in pieces:
                all_sw.extend(
                    swaths_in_piece(p, angle_deg=angle, spacing_m=spacing_m)
                )
            total_len = sum(s.length for s in all_sw)
            print(f"  angle={angle}: swaths={len(all_sw)}, "
                  f"total_length={total_len:.0f} m")
        print()


if __name__ == "__main__":
    # Простой прямоугольник без препятствий
    print("=== Rect 510 x 500 (no obstacles) ===")
    diagnose(Polygon([(0, 0), (510, 0), (510, 500), (0, 500)]))

    # Прямоугольник с препятствиями как в Moscow
    print("\n=== Rect 510 x 500 with 2 obstacles ===")
    poly = Polygon([(0, 0), (510, 0), (510, 500), (0, 500)])
    # Два препятствия внутри
    poly = poly.difference(
        Polygon([(200, 150), (230, 150), (230, 180), (200, 180)])
    )
    poly = poly.difference(
        Polygon([(400, 250), (450, 250), (450, 300), (400, 300)])
    )
    diagnose(poly)