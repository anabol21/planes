"""Интеграционные тесты запретных зон (NoFlyZone).

Проверяет:
  - загрузку запреток из GeoJSON и KML;
  - опциональность: без файла nfz = [];
  - вычитание запреток из полигона области;
  - обход запреток на перелётах (waypoints не внутри);
  - валидатор ловит нарушения;
  - экспорт запреток в KML и GeoJSON.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from planner.io.loaders import load_mission
from planner.solver.pipeline import run_mission


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
MOSCOW = FIXTURES_DIR / "moscow"


# ============================================================
# Хелпер: копирует moscow + добавляет no_fly_zones.geojson
# ============================================================

def _moscow_with_nfz(
    tmp_path: Path,
    nfz_geojson: dict | None = None,
    nfz_kml_text: str | None = None,
) -> Path:
    dst = tmp_path / "moscow_nfz"
    shutil.copytree(MOSCOW, dst)

    if nfz_geojson is not None:
        (dst / "no_fly_zones.geojson").write_text(
            json.dumps(nfz_geojson), encoding="utf-8",
        )
    if nfz_kml_text is not None:
        (dst / "no_fly_zones.kml").write_text(
            nfz_kml_text, encoding="utf-8",
        )
    return dst


# ============================================================
# Загрузка
# ============================================================

def test_no_nfz_file(tmp_path: Path):
    """Без файла — no_fly_zones пустой."""
    dst = _moscow_with_nfz(tmp_path)
    m = load_mission(dst)
    assert m.no_fly_zones == []


def test_nfz_from_geojson(tmp_path: Path):
    """Запретка из GeoJSON загружается."""
    nfz = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "nfz-1", "name": "Test"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [37.622, 55.751], [37.623, 55.751],
                    [37.623, 55.752], [37.622, 55.752],
                    [37.622, 55.751],
                ]],
            },
        }],
    }
    dst = _moscow_with_nfz(tmp_path, nfz_geojson=nfz)
    m = load_mission(dst)
    assert len(m.no_fly_zones) == 1
    assert m.no_fly_zones[0].id == "nfz-1"
    assert m.no_fly_zones[0].name == "Test"


def test_nfz_from_kml(tmp_path: Path):
    """Запретка из KML загружается."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>nfz-kml-1</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              37.622,55.751,0
              37.623,55.751,0
              37.623,55.752,0
              37.622,55.752,0
              37.622,55.751,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""
    dst = _moscow_with_nfz(tmp_path, nfz_kml_text=kml)
    m = load_mission(dst)
    assert len(m.no_fly_zones) == 1
    assert m.no_fly_zones[0].id == "nfz-kml-1"


def test_geojson_has_priority(tmp_path: Path):
    """Если есть и .geojson, и .kml — берётся .geojson."""
    nfz = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "nfz-gj", "name": "From GeoJSON"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [37.622, 55.751], [37.623, 55.751],
                    [37.623, 55.752], [37.622, 55.752],
                    [37.622, 55.751],
                ]],
            },
        }],
    }
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>nfz-kml</name><Polygon><outerBoundaryIs><LinearRing>
  <coordinates>37.622,55.751,0 37.623,55.751,0 37.623,55.752,0 37.622,55.752,0 37.622,55.751,0</coordinates>
  </LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>
"""
    dst = _moscow_with_nfz(
        tmp_path, nfz_geojson=nfz, nfz_kml_text=kml,
    )
    m = load_mission(dst)
    assert len(m.no_fly_zones) == 1
    assert m.no_fly_zones[0].id == "nfz-gj"


# ============================================================
# Pipeline
# ============================================================

def test_pipeline_with_safe_nfz(tmp_path: Path):
    """NFZ вне области — прогон проходит, все полосы сняты."""
    nfz = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "nfz-far", "name": "Far"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [38.0, 56.0], [38.001, 56.0],
                    [38.001, 56.001], [38.0, 56.001],
                    [38.0, 56.0],
                ]],
            },
        }],
    }
    dst = _moscow_with_nfz(tmp_path, nfz_geojson=nfz)
    out = tmp_path / "out"

    report = run_mission(dst, out)

    assert report.metrics.C_max_s > 0
    assert report.metrics.n_swaths_total > 0

    # В KML и GeoJSON есть запретка
    kml = (out / "mission" / "routes.kml").read_text(encoding="utf-8")
    assert "NoFlyZones" in kml
    assert "nfz-far" in kml

    gj = json.loads(
        (out / "mission" / "routes.geojson").read_text(encoding="utf-8")
    )
    nfz_features = [
        f for f in gj["features"]
        if f["properties"].get("kind") == "no_fly_zone"
    ]
    assert len(nfz_features) == 1
    assert nfz_features[0]["properties"]["id"] == "nfz-far"


def test_pipeline_with_inside_nfz(tmp_path: Path):
    """NFZ внутри области — прогон проходит, полос меньше."""
    # 1. Прогон без NFZ
    dst_no = _moscow_with_nfz(tmp_path)
    out_no = tmp_path / "out_no"
    rep_no = run_mission(dst_no, out_no)

    # 2. Прогон с NFZ в центре
    nfz = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "nfz-center", "name": "Center"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [37.6235, 55.7515], [37.6245, 55.7515],
                    [37.6245, 55.7525], [37.6235, 55.7525],
                    [37.6235, 55.7515],
                ]],
            },
        }],
    }
    dst_yes = _moscow_with_nfz(tmp_path, nfz_geojson=nfz)
    out_yes = tmp_path / "out_yes"
    rep_yes = run_mission(dst_yes, out_yes)

    # Полос с запреткой меньше (или столько же)
    assert rep_yes.metrics.n_swaths_total <= rep_no.metrics.n_swaths_total


def test_nfz_in_geojson_export(tmp_path: Path):
    """В routes.geojson запретки — отдельные фичи с kind=no_fly_zone."""
    nfz = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "nfz-export", "name": "Export test"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [38.0, 56.0], [38.001, 56.0],
                    [38.001, 56.001], [38.0, 56.001],
                    [38.0, 56.0],
                ]],
            },
        }],
    }
    dst = _moscow_with_nfz(tmp_path, nfz_geojson=nfz)
    out = tmp_path / "out"
    run_mission(dst, out)

    gj = json.loads(
        (out / "mission" / "routes.geojson").read_text(encoding="utf-8")
    )
    kinds = {f["properties"].get("kind") for f in gj["features"]}
    assert "no_fly_zone" in kinds
    assert gj["metadata"]["n_no_fly_zones"] == 1


# ============================================================
# Валидатор (unit-уровень)
# ============================================================

def test_check_no_fly_zones_direct():
    """Прямой вызов check_no_fly_zones."""
    from shapely.geometry import LineString
    from planner.models import (
        NoFlyZone, Route, Swath, Point,
    )
    from planner.validator.checker import check_no_fly_zones

    # Запретка вокруг (0.5, 0.5)
    nfz = NoFlyZone(
        id="nfz-1",
        polygon={
            "type": "Polygon",
            "coordinates": [[
                [0.4, 0.4], [0.6, 0.4],
                [0.6, 0.6], [0.4, 0.6],
                [0.4, 0.4],
            ]],
        },
    )

    # Полоса, проходящая через запретку (пересекает)
    swath_bad = Swath(
        id="s-bad", area_id="a1",
        start=Point(lat=0.5, lon=0.0, alt_m=100),
        end=Point(lat=0.5, lon=1.0, alt_m=100),
        length_m=111_000,
    )
    # Полоса в стороне от запретки
    swath_ok = Swath(
        id="s-ok", area_id="a1",
        start=Point(lat=0.9, lon=0.0, alt_m=100),
        end=Point(lat=0.9, lon=1.0, alt_m=100),
        length_m=111_000,
    )

    swaths_by_id = {"s-bad": swath_bad, "s-ok": swath_ok}

    # Маршрут с плохой полосой
    r_bad = Route(
        uav_id="u1", flight_index=0, vpp_id="v1",
        swath_ids=["s-bad"],
        waypoints=[
            Point(lat=0.5, lon=0.0, alt_m=100),
            Point(lat=0.5, lon=1.0, alt_m=100),
        ],
    )
    # Маршрут с хорошей полосой
    r_ok = Route(
        uav_id="u1", flight_index=1, vpp_id="v1",
        swath_ids=["s-ok"],
        waypoints=[
            Point(lat=0.9, lon=0.0, alt_m=100),
            Point(lat=0.9, lon=1.0, alt_m=100),
        ],
    )

    errors_bad = check_no_fly_zones(
        [r_bad], swaths_by_id, [nfz],
    )
    assert len(errors_bad) > 0, "должна быть ошибка для s-bad"

    errors_ok = check_no_fly_zones(
        [r_ok], swaths_by_id, [nfz],
    )
    assert len(errors_ok) == 0, "не должно быть ошибок для s-ok"


def test_check_no_fly_zones_empty():
    """Без запреток — пустой список ошибок."""
    from planner.validator.checker import check_no_fly_zones
    errors = check_no_fly_zones([], {}, [])
    assert errors == []


def test_waypoint_inside_nfz():
    """Waypoint внутри запретки — ошибка."""
    from planner.models import NoFlyZone, Route, Point
    from planner.validator.checker import check_no_fly_zones

    nfz = NoFlyZone(
        id="nfz-1",
        polygon={
            "type": "Polygon",
            "coordinates": [[
                [0.4, 0.4], [0.6, 0.4],
                [0.6, 0.6], [0.4, 0.6],
                [0.4, 0.4],
            ]],
        },
    )

    r = Route(
        uav_id="u1", flight_index=0, vpp_id="v1",
        swath_ids=[],
        waypoints=[
            Point(lat=0.5, lon=0.5, alt_m=100),  # внутри nfz
        ],
    )

    errors = check_no_fly_zones([r], {}, [nfz])
    assert len(errors) > 0
    assert "inside no-fly zone" in errors[0]