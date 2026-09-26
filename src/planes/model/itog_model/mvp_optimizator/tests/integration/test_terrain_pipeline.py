"""Offline local-GeoTIFF terrain flow through the Grisha optimizer."""

import json
from pathlib import Path
import shutil

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from planner.io.loaders import load_mission
from planner.solver.pipeline import _generate_all_swaths, run_mission


SOURCE_FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_local_geotiff_to_profile_physics_routing_validator_and_outputs(tmp_path):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(SOURCE_FIXTURES, fixtures)
    raster_path = fixtures / "terrain.tif"
    rows = np.linspace(104.0, 100.0, 20, dtype="float32")[:, None]
    data = np.repeat(rows, 20, axis=1)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(37.619, 55.749, 37.629, 55.756, 20, 20),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(data, 1)

    params_path = fixtures / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))
    params.update(
        dem_file="terrain.tif",
        dem_crs="EPSG:4326",
        dem_horizontal_unit="degree",
        dem_elevation_unit="metre",
        terrain_sample_step_m=25.0,
        angles_deg=[0.0],
        attempts_max=1,
    )
    params_path.write_text(json.dumps(params), encoding="utf-8")

    mission = load_mission(fixtures)
    swaths_by_area, _ = _generate_all_swaths(mission, 0.0)
    swaths = [swath for group in swaths_by_area.values() for swath in group]
    assert swaths
    assert all(len(swath.segments) >= 2 for swath in swaths)
    for swath in swaths:
        assert all(
            segment.h_asl_m == segment.dem_m + segment.h_agl_m
            for segment in swath.segments
        )
        assert swath.terrain_distance_3d_m >= swath.length_m * 0.99
        assert swath.t_survey_actual_s > 0
        assert swath.e_survey_actual_wh > 0

    report = run_mission(fixtures, tmp_path / "out")
    assert report.metrics.n_swaths_total > 0
    assert report.metrics.energy_total_wh > 0
    assert (tmp_path / "out/mission/report.json").is_file()
    assert (tmp_path / "out/mission/routes.kml").is_file()
