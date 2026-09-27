"""Диагностика F2C: что именно заставляет его виснуть на Moscow.

Проверяет F2C на:
  - чистом прямоугольнике (без obstacles);
  - внешнем контуре после difference (без дырок);
  - полигоне с дырками (как есть);
  - разных spacing.

Запуск:
    python3 scripts/diagnose_f2c.py
"""

from __future__ import annotations

import time
from pathlib import Path

from shapely.geometry import Polygon, shape

from planner.io.loaders import load_mission
from planner.geometry.f2c_backend import (
    _generate_for_single_polygon,
    _vertex_count,
    SIMPLIFY_TOLERANCE_M,
)


FIXTURES = Path("tests/fixtures/moscow")


def _timed(label: str, fn, *args, **kwargs) -> None:
    """Запускает fn, печатает время и число полос."""
    print(f"\n=== {label} ===")
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        dt = time.time() - t0
        print(f"  OK: {len(result)} полос за {dt:.2f}s")
    except Exception as e:
        dt = time.time() - t0
        print(f"  FAIL за {dt:.2f}s: {type(e).__name__}: {e}")


def main():
    mission = load_mission(FIXTURES)
    area = mission.areas[0]

    # Локальная ENU-проекция
    from planner.utils.geo import make_local_transformer
    poly_wgs = shape(area.polygon)
    c = poly_wgs.centroid
    fwd, inv = make_local_transformer(c.x, c.y)

    # Базовый полигон
    poly_m = Polygon(
        [fwd.transform(x, y) for x, y in poly_wgs.exterior.coords],
        holes=[
            [fwd.transform(x, y) for x, y in interior.coords]
            for interior in poly_wgs.interiors
        ],
    )
    print(f"Исходный полигон: {poly_m.geom_type}, "
          f"{_vertex_count(poly_m)} вершин")
    print(f"  area: {poly_m.area:.0f} m²")

    # Вычитаем препятствия с buffer 20 м
    obstacle_buffer_m = mission.params.obstacle_buffer_m
    for obs in mission.obstacles:
        obs_poly = shape(obs.polygon)
        obs_m = Polygon(
            [fwd.transform(x, y) for x, y in obs_poly.exterior.coords]
        )
        if obstacle_buffer_m > 0:
            obs_m = obs_m.buffer(obstacle_buffer_m)
        print(f"  obstacle {obs.id}: {_vertex_count(obs_m)} вершин "
              f"после buffer({obstacle_buffer_m})")
        poly_m = poly_m.difference(obs_m)

    print(f"\nПосле difference: {poly_m.geom_type}, "
          f"{_vertex_count(poly_m)} вершин")
    if poly_m.geom_type == "Polygon":
        print(f"  exterior: {len(poly_m.exterior.coords)} вершин")
        for i, hole in enumerate(poly_m.interiors):
            print(f"  hole {i}: {len(hole.coords)} вершин")

    spacing_m = 126.0  # реальный spacing для Moscow

    # --- ТЕСТ 1: чистый прямоугольник без obstacles ---
    poly_clean = Polygon(
        [fwd.transform(x, y) for x, y in poly_wgs.exterior.coords]
    )
    print(f"\n[Тест 1] Чистый прямоугольник: "
          f"{_vertex_count(poly_clean)} вершин")
    _timed(
        "F2C на чистом прямоугольнике",
        _generate_for_single_polygon, poly_clean, spacing_m, 0.0,
    )

    # --- ТЕСТ 2: полигон после difference, но БЕЗ дырок ---
    if poly_m.geom_type == "Polygon":
        poly_no_holes = Polygon(poly_m.exterior.coords)
        print(f"\n[Тест 2] Внешний контур без дырок: "
              f"{_vertex_count(poly_no_holes)} вершин")
        _timed(
            "F2C на внешнем контуре",
            _generate_for_single_polygon, poly_no_holes, spacing_m, 0.0,
        )

    # --- ТЕСТ 3: полигон С дырками (как есть) ---
    print(f"\n[Тест 3] Полигон с дырками: "
          f"{_vertex_count(poly_m)} вершин")
    _timed(
        "F2C с дырками",
        _generate_for_single_polygon, poly_m, spacing_m, 0.0,
    )

    # --- ТЕСТ 4: с упрощением до 5 м ---
    poly_s5 = poly_m.simplify(5.0, preserve_topology=True)
    print(f"\n[Тест 4] С simplify(5.0): "
          f"{_vertex_count(poly_s5)} вершин")
    _timed(
        "F2C с simplify 5 м",
        _generate_for_single_polygon, poly_s5, spacing_m, 0.0,
    )


if __name__ == "__main__":
    main()