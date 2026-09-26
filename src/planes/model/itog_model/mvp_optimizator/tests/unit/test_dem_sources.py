"""Fail-closed KML and GeoTIFF provider tests."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from planner.io.dem import GeoTiffDEM, KMLDem, TerrainDataError, load_dem


def write_kml(path: Path, coordinate_text: str) -> Path:
    path.write_text(
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">'
        f"<Document><Placemark><Point><coordinates>{coordinate_text}"
        "</coordinates></Point></Placemark></Document></kml>",
        encoding="utf-8",
    )
    return path


def write_raster(path: Path, data: np.ndarray, *, nodata=-9999.0) -> Path:
    transform = from_bounds(37.60, 55.70, 37.64, 55.74, data.shape[1], data.shape[0])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(data.astype("float32"), 1)
    return path


def test_valid_kml_and_explicit_units(tmp_path):
    path = write_kml(tmp_path / "terrain.kml", "37.62,55.72,123.5")
    dem = load_dem(
        path,
        crs="EPSG:4326",
        horizontal_unit="degree",
        elevation_unit="metre",
    )
    assert isinstance(dem, KMLDem)
    assert dem.h(55.72, 37.62) == pytest.approx(123.5)


@pytest.mark.parametrize(
    "contents",
    [
        "<not-xml",
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"/>',
    ],
)
def test_invalid_or_empty_kml_fails_closed(tmp_path, contents):
    path = tmp_path / "bad.kml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(TerrainDataError):
        load_dem(
            path,
            crs="EPSG:4326",
            horizontal_unit="degree",
            elevation_unit="metre",
        )


@pytest.mark.parametrize("value", ["", "nan", "inf", "broken"])
def test_invalid_kml_elevation_fails_closed(tmp_path, value):
    path = write_kml(tmp_path / "bad.kml", f"37.62,55.72,{value}")
    with pytest.raises(TerrainDataError):
        load_dem(
            path,
            crs="EPSG:4326",
            horizontal_unit="degree",
            elevation_unit="metre",
        )


def test_requested_missing_terrain_does_not_become_flat(tmp_path):
    with pytest.raises(TerrainDataError):
        load_dem(
            tmp_path / "missing.kml",
            crs="EPSG:4326",
            horizontal_unit="degree",
            elevation_unit="metre",
        )


def test_geotiff_bilinear_interpolation_and_bounds(tmp_path):
    path = write_raster(
        tmp_path / "terrain.tif",
        np.array([[100.0, 200.0], [300.0, 400.0]]),
    )
    dem = GeoTiffDEM(path, expected_crs="EPSG:4326")
    assert dem.h(55.72, 37.62) == pytest.approx(250.0, abs=1e-3)
    assert dem.h_min() == 100.0
    assert dem.h_max() == 400.0
    with pytest.raises(TerrainDataError, match="outside"):
        dem.h(55.80, 37.62)


def test_geotiff_nodata_fails_closed(tmp_path):
    path = write_raster(
        tmp_path / "nodata.tif",
        np.array([[100.0, -9999.0], [300.0, 400.0]]),
    )
    dem = GeoTiffDEM(path, expected_crs="EPSG:4326")
    with pytest.raises(TerrainDataError, match="nodata"):
        dem.h(55.72, 37.62)


def test_corrupt_geotiff_fails_closed(tmp_path):
    path = tmp_path / "bad.tif"
    path.write_bytes(b"not a raster")
    with pytest.raises(TerrainDataError):
        GeoTiffDEM(path, expected_crs="EPSG:4326")
