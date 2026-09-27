"""Профиль рельефа и профиль полёта БВС (2 subplot).

Запуск:
    python3 scripts/plot_terrain_profile.py tests/fixtures out/terrain/terrain_profile.png
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from planner.io import load_mission
from planner.io.catalog import get_default_catalog
from planner.geometry.generate import generate_swaths_for_area


def _save_fig_safe(fig, out_path: Path, dpi: int = 110) -> None:
    """
    Сохраняет фигуру через BytesIO — обходит проблемы с OneDrive/Windows volume.
    """
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    except Exception as e:
        print(f"[warn] bbox_inches failed: {e}. Retry without.")
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())


def main(fixtures_dir: str, out_path: str):
    mission = load_mission(fixtures_dir)
    catalog = get_default_catalog()
    uav = mission.uavs[0]
    cam = catalog.get_camera(uav.camera_id)

    # Физика первого борта — для скоростей
    from planner.physics import build_physics_model, build_physics_params
    pp = build_physics_params(
        uav, catalog, reserve_fraction=mission.params.reserve_fraction
    )
    model = build_physics_model(pp)
    P_nominal = model.power_w(pp.v_air_mps, mission.params.wind.speed_mps)

    angle = mission.params.angles_deg[0]

    all_swaths = []
    for area in mission.areas:
        swaths, h_agl = generate_swaths_for_area(
            area=area,
            obstacles=mission.obstacles,
            angle_deg=angle,
            gsd_cm_per_px=mission.params.gsd_cm_per_px,
            camera=cam,
            decomposition=mission.params.decomposition.value,
            dem=mission.dem,
            v_climb_mps=pp.v_climb_mps,
            v_descent_mps=pp.v_descent_mps,
            v_min_mps=pp.v_min_mps,
            v_survey_mps=pp.v_survey_mps,
            mass_kg=pp.mass_kg,
            P_nominal_w=P_nominal,
        )
        all_swaths.extend(swaths)

    if not all_swaths:
        print("No swaths")
        sys.exit(1)

    x, dem_vals, drone_vals = [], [], []
    swath_boundaries = []
    cum = 0.0

    for s in all_swaths:
        if not s.segments:
            continue
        for seg in s.segments:
            x.append(cum + seg.dist_from_start_m)
            dem_vals.append(seg.dem_m)
            drone_vals.append(seg.h_asl_m)
        cum += s.length_m
        swath_boundaries.append(len(x))

    x = np.array(x)
    dem_vals = np.array(dem_vals)
    drone_vals = np.array(drone_vals)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [2, 3]},
    )

    # Верх: рельеф
    ax1.fill_between(x, 0, dem_vals, color="#8b6914", alpha=0.6,
                     label="Рельеф (DEM)")
    ax1.plot(x, dem_vals, color="#5c4608", linewidth=1.2)
    ax1.set_ylabel("Рельеф, м ASL", fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left", fontsize=10)
    ax1.set_title(
        f"Профиль вдоль маршрута — угол {angle:.0f}°, "
        f"h_agl = {all_swaths[0].h_agl_m:.0f} м",
        fontsize=13, fontweight="bold",
    )

    # Низ: профиль БВС
    ax2.fill_between(x, 0, drone_vals, color="#4a90e2", alpha=0.35,
                     label="Высота БВС")
    ax2.plot(x, drone_vals, color="#1e5fa8", linewidth=2.0)

    for idx in swath_boundaries[:-1]:
        if idx < len(x):
            ax2.axvline(x[idx], color="gray", linestyle="--",
                        alpha=0.4, linewidth=0.8)

    agl = drone_vals - dem_vals
    agl_min_idx = int(np.argmin(agl))
    ax2.annotate(
        f"min AGL = {agl.min():.0f} м",
        xy=(x[agl_min_idx], drone_vals[agl_min_idx]),
        xytext=(20, 20), textcoords="offset points",
        fontsize=10, color="darkred",
        arrowprops=dict(arrowstyle="->", color="darkred"),
    )

    ax2.set_xlabel("Пройденный путь вдоль маршрута, м", fontsize=12)
    ax2.set_ylabel("Высота БВС, м ASL", fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper left", fontsize=10)

    # Метки полос
    for i, idx in enumerate(swath_boundaries):
        start_x = 0 if i == 0 else x[swath_boundaries[i - 1] - 1]
        end_x = x[idx - 1] if idx > 0 else 0
        mid_x = (start_x + end_x) / 2
        y_top = ax2.get_ylim()[1]
        ax2.text(mid_x, y_top * 0.99, f"S{i+1}",
                 ha="center", va="top", fontsize=9, alpha=0.7)

    plt.tight_layout()

    out = Path(out_path)
    _save_fig_safe(fig, out, dpi=110)
    plt.close(fig)

    print(f"  profile → {out}")
    print(f"  swaths: {len(all_swaths)}")
    print(f"  DEM range: {dem_vals.min():.0f} .. {dem_vals.max():.0f} m")
    print(f"  drone ASL range: {drone_vals.min():.0f} .. {drone_vals.max():.0f} m")
    print(f"  min AGL: {agl.min():.1f} m")


if __name__ == "__main__":
    fixtures = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "out/terrain/terrain_profile.png"
    main(fixtures, out_path)