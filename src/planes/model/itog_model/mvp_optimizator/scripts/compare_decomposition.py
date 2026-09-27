"""Сравнение trapezoid vs triangulation на одном сценарии.

Запуск:
    python3 scripts/compare_decomposition.py tests/fixtures
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from planner.io.loaders import load_mission
from planner.io.catalog import get_default_catalog
from planner.geometry.generate import generate_swaths_for_area


def run_method(mission, method: str) -> dict:
    catalog = get_default_catalog()
    uav = mission.uavs[0]
    camera = catalog.get_camera(uav.camera_id)

    results = []
    for area in mission.areas:
        swaths, h_agl = generate_swaths_for_area(
            area=area,
            obstacles=mission.obstacles,
            angle_deg=0.0,
            gsd_cm_per_px=mission.params.gsd_cm_per_px,
            camera=camera,
            decomposition=method,
        )
        results.append({
            "area_id": area.id,
            "h_agl_m": round(h_agl, 1),
            "n_swaths": len(swaths),
            "total_length_m": round(sum(s.length_m for s in swaths), 1),
        })

    return {
        "method": method,
        "areas": results,
        "n_swaths_total": sum(r["n_swaths"] for r in results),
        "total_length_m": round(sum(r["total_length_m"] for r in results), 1),
    }


def main(fixtures_dir: str) -> None:
    mission = load_mission(fixtures_dir)
    print(f"Scenario: {len(mission.areas)} areas, {len(mission.obstacles)} obstacles")
    print(f"GSD: {mission.params.gsd_cm_per_px} cm/px, angle: 0")
    print()

    rows = []
    for method in ("trapezoid", "triangulation"):
        r = run_method(mission, method)
        rows.append(r)
        print(f"[{method}]")
        for a in r["areas"]:
            print(f"  area={a['area_id']} h={a['h_agl_m']}m "
                  f"n_swaths={a['n_swaths']} L={a['total_length_m']}m")
        print(f"  total: {r['n_swaths_total']} swaths, "
              f"{r['total_length_m']} m")
        print()

    # Сравнение
    t = rows[0]
    tri = rows[1]
    diff = tri["n_swaths_total"] - t["n_swaths_total"]
    print("Diff:")
    print(f"  swaths: {t['n_swaths_total']} → {tri['n_swaths_total']} "
          f"({'+' if diff >= 0 else ''}{diff})")
    print(f"  length: {t['total_length_m']} → {tri['total_length_m']}")


if __name__ == "__main__":
    fixtures = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"
    main(fixtures)