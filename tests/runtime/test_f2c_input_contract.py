"""F2C input contract: no frontend strip angle, generateBestSwaths."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from planes.runtime import fields2cover_engine as engine
from planes.runtime.geo_mission import _core_symbols, _params


class GeoMissionParamsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.symbols = _core_symbols()

    def test_ignores_strip_direction_and_leaves_angles_empty(self) -> None:
        params = _params(
            {
                "gsd_cm_per_px": 3,
                "survey": {
                    "side_overlap": 0.6,
                    "forward_overlap": 0.7,
                    "strip_direction_deg": 45,
                },
                "wind": {"speed_ms": 2, "direction_deg": 90},
            },
            "min_time",
            Path("/tmp/dem.tif"),
            self.symbols,
        )
        self.assertEqual(list(params.angles_deg or []), [])
        self.assertEqual(params.decomposition.value, "fields2cover")
        self.assertEqual(params.gsd_cm_per_px, 3.0)
        self.assertEqual(params.overlap_x, 0.6)
        self.assertEqual(params.overlap_long, 0.7)
        self.assertEqual(params.wind.speed_mps, 2.0)
        self.assertEqual(params.wind.direction_deg, 90.0)

    def test_missing_strip_direction_is_not_an_error(self) -> None:
        params = _params(
            {
                "gsd_cm_per_px": 3,
                "survey": {"side_overlap": 0.6, "forward_overlap": 0.7},
                "wind": {"speed_ms": 1, "direction_deg": 0},
            },
            "min_flight_hours",
            Path("/tmp/dem.tif"),
            self.symbols,
        )
        self.assertEqual(list(params.angles_deg or []), [])

    def test_wind_gsd_and_overlaps_stay_required(self) -> None:
        base = {
            "gsd_cm_per_px": 3,
            "survey": {"side_overlap": 0.6, "forward_overlap": 0.7},
            "wind": {"speed_ms": 1, "direction_deg": 10},
        }
        cases = [
            {**base, "gsd_cm_per_px": None},
            {**base, "survey": {"forward_overlap": 0.7}},
            {**base, "survey": {"side_overlap": 0.6}},
            {**base, "wind": {"direction_deg": 10}},
            {**base, "wind": {"speed_ms": 1}},
        ]
        for scenario in cases:
            with self.subTest(scenario=scenario):
                with self.assertRaises(ValueError):
                    _params(scenario, "min_time", Path("/tmp/dem.tif"), self.symbols)


class Fields2CoverEngineAutoAngleTest(unittest.TestCase):
    def test_swaths_use_generate_best_not_fixed_angle(self) -> None:
        calls: list[str] = []

        class FakePoint:
            def __init__(self, x: float, y: float) -> None:
                self._x = x
                self._y = y

            def getX(self) -> float:
                return self._x

            def getY(self) -> float:
                return self._y

        class FakeSwath:
            def startPoint(self) -> FakePoint:
                return FakePoint(0.0, 0.0)

            def endPoint(self) -> FakePoint:
                return FakePoint(10.0, 0.0)

            def length(self) -> float:
                return 10.0

        class FakeSwaths:
            def flatten(self) -> FakeSwaths:
                return self

            def size(self) -> int:
                return 1

            def at(self, index: int) -> FakeSwath:
                del index
                return FakeSwath()

        class FakeBF:
            def generateBestSwaths(self, obj, spacing, cells):
                del cells
                calls.append(f"best:{type(obj).__name__}:{spacing}")
                return FakeSwaths()

            def generateSwaths(self, *args, **kwargs):
                del args, kwargs
                raise AssertionError("generateSwaths must not run on the auto-F2C path")

        class FakeF2C:
            OBJ_NSwathModified = type("OBJ_NSwathModified", (), {})
            OBJ_NSwath = type("OBJ_NSwath", (), {})
            OBJ_SwathLength = type("OBJ_SwathLength", (), {})
            Cells = MagicMock
            SG_BruteForce = FakeBF

            class RP_Boustrophedon:
                def genSortedSwaths(self, flat):
                    return flat

        original = engine._fields2cover
        original_cell = engine._cell
        engine._fields2cover = lambda: FakeF2C
        engine._cell = lambda f2c, poly: object()
        try:
            from shapely.geometry import Polygon

            found = engine._swaths([Polygon([(0, 0), (40, 0), (40, 20), (0, 20)])], 12.0)
        finally:
            engine._fields2cover = original
            engine._cell = original_cell
        self.assertEqual(calls, ["best:OBJ_NSwathModified:12.0"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].length_m, 10.0)

    def test_plan_does_not_read_angles_deg_zero(self) -> None:
        """Empty angles must not IndexError on angles_deg[0]."""
        mission = SimpleNamespace(
            params=SimpleNamespace(angles_deg=[]),
            vpps=[SimpleNamespace(lon=37.6, lat=55.75)],
            areas=[],
            obstacles=[],
        )
        token = engine.bind_context(
            engine.EngineContext(
                deadline=1e18,
                boards=(
                    engine.BoardCamera(
                        uav_id="БВС 1",
                        vpp_id="аэродром 1",
                        lat=55.75,
                        lon=37.6,
                        endurance_s=1200.0,
                        speed_m_s=12.0,
                        spacing_m=20.0,
                        h_agl_m=80.0,
                    ),
                ),
            )
        )
        try:
            self.assertIsNone(engine.plan(mission))
        finally:
            engine.reset_context(token)


if __name__ == "__main__":
    unittest.main()
