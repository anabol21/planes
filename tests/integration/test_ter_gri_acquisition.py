"""Offline OpenTopography acquisition and future product-flow tests."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.parse

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from planes.integration.terrain import (
    TerrainAcquisitionError,
    acquire_terrain_for_area,
    bbox_from_geojson,
)


ROOT = Path(__file__).resolve().parents[2]
OPTIMIZER = ROOT / "src/planes/model/itog_model/mvp_optimizator"
AREA = OPTIMIZER / "tests/fixtures/area.geojson"


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class PartialResponse(Response):
    def __init__(self, payload):
        super().__init__(payload)
        self.calls = 0

    def read(self, size=-1):
        self.calls += 1
        if self.calls > 1:
            raise OSError("simulated interrupted response")
        return super().read(8)


def geotiff_bytes(value=120.0):
    data = np.full((16, 16), value, dtype="float32")
    transform = from_bounds(37.619, 55.749, 37.629, 55.756, 16, 16)
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=16,
            width=16,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            nodata=-9999.0,
        ) as dataset:
            dataset.write(data, 1)
        return memory.read()


def test_bbox_is_union_of_survey_polygons_and_padding_is_explicit():
    bounds = bbox_from_geojson(AREA, crs="EPSG:4326")
    assert (bounds.west, bounds.south, bounds.east, bounds.north) == pytest.approx(
        (37.620, 55.750, 37.628, 55.7545)
    )
    padded = bbox_from_geojson(AREA, crs="EPSG:4326", padding_m=10.0)
    assert padded.west < bounds.west
    assert padded.east > bounds.east
    assert padded.south < bounds.south
    assert padded.north > bounds.north


def test_bbox_unions_multiple_survey_features():
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10, 20], [11, 20], [11, 21], [10, 20]]],
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[12, 19], [13, 19], [13, 22], [12, 19]]],
                },
            },
        ],
    }
    bounds = bbox_from_geojson(data, crs="EPSG:4326")
    assert (bounds.west, bounds.south, bounds.east, bounds.north) == (10, 19, 13, 22)


def test_missing_api_key_stops_before_http(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    with pytest.raises(TerrainAcquisitionError, match="not visible"):
        acquire_terrain_for_area(
            AREA,
            survey_crs="EPSG:4326",
            cache_dir=tmp_path,
            opener=lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
        )


def test_request_parameters_and_cache_hit(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "test-secret-not-literal-product-key")
    calls = []

    def opener(request, timeout):
        calls.append(request)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        assert query["demtype"] == ["COP30"]
        assert query["outputFormat"] == ["GTiff"]
        assert query["west"] == ["37.62000000"]
        assert query["east"] == ["37.62800000"]
        assert query["south"] == ["55.75000000"]
        assert query["north"] == ["55.75450000"]
        assert query["API_Key"] == [os.environ["OPENTOPOGRAPHY_API_KEY"]]
        return Response(geotiff_bytes())

    first = acquire_terrain_for_area(
        AREA,
        survey_crs="EPSG:4326",
        cache_dir=tmp_path,
        opener=opener,
    )
    assert first.name.startswith("COP30_") and first.suffix == ".tif"
    assert len(calls) == 1

    second = acquire_terrain_for_area(
        AREA,
        survey_crs="EPSG:4326",
        cache_dir=tmp_path,
        opener=lambda *args, **kwargs: pytest.fail("cache hit made HTTP request"),
    )
    assert second == first
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [b"", b"<html>error</html>", b'{"error":true}', b"bad-tiff"])
def test_invalid_response_never_creates_cache_entry(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "secret-for-error-test")
    with pytest.raises(TerrainAcquisitionError):
        acquire_terrain_for_area(
            AREA,
            survey_crs="EPSG:4326",
            cache_dir=tmp_path,
            opener=lambda *args, **kwargs: Response(payload),
        )
    assert not list(tmp_path.glob("*.tif"))
    assert not list(tmp_path.glob("*.part"))


def test_http_error_is_sanitized_and_secret_free(monkeypatch, tmp_path):
    secret = "marker-that-must-not-escape"
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", secret)

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "rate", {}, None)

    with pytest.raises(TerrainAcquisitionError) as captured:
        acquire_terrain_for_area(
            AREA,
            survey_crs="EPSG:4326",
            cache_dir=tmp_path,
            opener=fail,
        )
    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)
    assert not list(tmp_path.iterdir())


def test_partial_download_is_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "partial-test-secret")
    with pytest.raises(TerrainAcquisitionError):
        acquire_terrain_for_area(
            AREA,
            survey_crs="EPSG:4326",
            cache_dir=tmp_path,
            opener=lambda *args, **kwargs: PartialResponse(geotiff_bytes()),
        )
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*.tif"))


def test_mock_acquisition_to_optimizer_end_to_end(monkeypatch, tmp_path):
    """area -> mocked COP30 -> cache -> provider -> optimizer -> report/routes."""
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "mock-e2e-secret")
    raster = acquire_terrain_for_area(
        AREA,
        survey_crs="EPSG:4326",
        cache_dir=tmp_path / "cache",
        opener=lambda *args, **kwargs: Response(geotiff_bytes(110.0)),
    )

    fixtures = tmp_path / "fixtures"
    shutil.copytree(OPTIMIZER / "tests/fixtures", fixtures)
    params_path = fixtures / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))
    params.update(
        dem_file=str(raster),
        dem_crs="EPSG:4326",
        dem_horizontal_unit="degree",
        dem_elevation_unit="metre",
        terrain_sample_step_m=25.0,
        angles_deg=[0.0],
        attempts_max=1,
    )
    params_path.write_text(json.dumps(params), encoding="utf-8")

    sys.path.insert(0, str(OPTIMIZER / "src"))
    try:
        from planner.io.loaders import load_mission
        from planner.solver.pipeline import run_mission

        mission = load_mission(fixtures)
        assert mission.dem.h(55.752, 37.624) == pytest.approx(110.0)
        report = run_mission(fixtures, tmp_path / "out")
    finally:
        sys.path.remove(str(OPTIMIZER / "src"))
    assert report.metrics.n_swaths_total > 0
    assert (tmp_path / "out/mission/report.json").is_file()
    assert (tmp_path / "out/mission/routes.kml").is_file()
