"""Wave B packer: foreign pads, recharge, UAV–UAV separation.

Loads ``tools/f2c_iso/iso_src/wave_b.py`` directly. No fields2cover embed.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from support import REPO


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Python 3.12 dataclasses look up sys.modules[cls.__module__].
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_wave_b():
    return _load_module(
        "wave_b_under_test",
        REPO / "tools" / "f2c_iso" / "iso_src" / "wave_b.py",
    )


class FlagParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wb = _load_wave_b()

    def test_defaults(self) -> None:
        flags = self.wb.read_wave_b_flags({})
        self.assertTrue(flags.allow_recharge)
        self.assertTrue(flags.allow_foreign_landing)
        self.assertFalse(flags.allow_foreign_takeoff)
        self.assertEqual(flags.min_separation_m, 50.0)
        self.assertEqual(flags.time_window_s, 0.0)
        self.assertIsNone(flags.recharge_time_s_override)

    def test_power_and_zero_separation(self) -> None:
        flags = self.wb.read_wave_b_flags(
            {
                "power": {"allow_recharge": False, "recharge_time_s": 12},
                "min_separation_m": 0,
                "allow_foreign_takeoff": True,
            }
        )
        self.assertFalse(flags.allow_recharge)
        self.assertEqual(flags.recharge_time_s_override, 12.0)
        self.assertEqual(flags.min_separation_m, 0.0)
        self.assertTrue(flags.allow_foreign_takeoff)

    def test_recharge_override_beats_catalog(self) -> None:
        flags = self.wb.read_wave_b_flags({"recharge_time_s": 9})
        self.assertEqual(
            self.wb.read_recharge_time_s(
                {"recharge_time_s": {"value": 6300}},
                {"recharge_time_s": 3},
                flags,
            ),
            9.0,
        )
        self.assertEqual(
            self.wb.read_recharge_time_s(
                {"recharge_time_s": {"value": 6300}},
                None,
                self.wb.WaveBFlags(),
            ),
            6300.0,
        )


class ForeignLandingTest(unittest.TestCase):
    """B1 — land (and optionally take off) at a closer pad."""

    def setUp(self) -> None:
        self.wb = _load_wave_b()
        self.home = self.wb.Pad("home", (0.0, 0.0))
        self.far = self.wb.Pad("far", (1000.0, 0.0))
        self.pads = [self.home, self.far]
        # Swath sits next to the far pad.
        self.swaths = [self.wb.Swath((990.0, 10.0), (990.0, 40.0), 30.0)]

    def test_lands_on_closer_foreign_pad(self) -> None:
        packed = self.wb.pack_board(
            "uav-1",
            self.swaths,
            self.pads,
            "home",
            endurance_s=10_000.0,
            speed_m_s=10.0,
            allow_foreign_landing=True,
            allow_foreign_takeoff=False,
        )
        self.assertEqual(len(packed.sorties), 1)
        self.assertEqual(len(packed.uncovered), 0)
        sortie = packed.sorties[0]
        self.assertEqual(sortie.takeoff_pad_id, "home")
        self.assertEqual(sortie.landing_pad_id, "far")
        home_return = self.wb.pack_board(
            "uav-1",
            self.swaths,
            self.pads,
            "home",
            endurance_s=10_000.0,
            speed_m_s=10.0,
            allow_foreign_landing=False,
            allow_foreign_takeoff=False,
        ).sorties[0]
        self.assertEqual(home_return.landing_pad_id, "home")
        self.assertLess(sortie.flight_time_s, home_return.flight_time_s)

    def test_foreign_takeoff_when_allowed(self) -> None:
        packed = self.wb.pack_board(
            "uav-1",
            self.swaths,
            self.pads,
            "home",
            endurance_s=10_000.0,
            speed_m_s=10.0,
            allow_foreign_landing=True,
            allow_foreign_takeoff=True,
        )
        self.assertEqual(packed.sorties[0].takeoff_pad_id, "far")
        self.assertEqual(packed.sorties[0].landing_pad_id, "far")

    def test_home_wins_a_distance_tie(self) -> None:
        pads = [self.wb.Pad("home", (0.0, 0.0)), self.wb.Pad("other", (10.0, 0.0))]
        chosen = self.wb.choose_pad((5.0, 0.0), pads, "home", allowed=True)
        self.assertEqual(chosen.id, "home")


class RechargeTest(unittest.TestCase):
    """B2 — charge gaps in makespan; fail-without-recharge."""

    def setUp(self) -> None:
        self.wb = _load_wave_b()
        self.home = self.wb.Pad("home", (0.0, 0.0))
        # Two nearby swaths. One home-return sortie is ~17–19 s at 10 m/s;
        # both in one sortie exceed ~20 s. Endurance 19.5 splits them.
        self.swaths = [
            self.wb.Swath((80.0, 0.0), (80.0, 10.0), 10.0),
            self.wb.Swath((90.0, 0.0), (90.0, 10.0), 10.0),
        ]

    def test_allow_recharge_adds_gap_to_makespan(self) -> None:
        packed = self.wb.pack_board(
            "board-a",
            self.swaths,
            [self.home],
            "home",
            endurance_s=19.5,
            speed_m_s=10.0,
            allow_recharge=True,
        )
        self.assertEqual(len(packed.uncovered), 0)
        self.assertEqual(len(packed.sorties), 2)
        self.wb.apply_recharge_timeline(packed.sorties, {"board-a": 100.0})
        air = self.wb.total_flight_time_s(packed.sorties)
        gap = self.wb.recharge_gap_s(packed.sorties)
        span = self.wb.makespan_s(packed.sorties)
        self.assertEqual(gap, 100.0)
        self.assertGreater(air, 0.0)
        self.assertAlmostEqual(span, air + 100.0, places=5)
        self.assertGreater(packed.sorties[1].start_time_s, packed.sorties[0].flight_time_s)

    def test_disallow_recharge_leaves_uncovered(self) -> None:
        packed = self.wb.pack_board(
            "board-a",
            self.swaths,
            [self.home],
            "home",
            endurance_s=19.5,
            speed_m_s=10.0,
            allow_recharge=False,
        )
        self.assertEqual(len(packed.sorties), 1)
        self.assertGreaterEqual(len(packed.uncovered), 1)
        self.assertTrue(any("allow_recharge=false" in line for line in packed.limitations))

    def test_single_swath_over_endurance_is_uncovered_even_with_recharge(self) -> None:
        huge = [self.wb.Swath((0.0, 0.0), (1000.0, 0.0), 1000.0)]
        packed = self.wb.pack_board(
            "board-a",
            huge,
            [self.home],
            "home",
            endurance_s=5.0,
            speed_m_s=10.0,
            allow_recharge=True,
        )
        self.assertEqual(packed.sorties, [])
        self.assertEqual(len(packed.uncovered), 1)


class SeparationTest(unittest.TestCase):
    """B3 — detect a space–time conflict and delay until clean."""

    def setUp(self) -> None:
        self.wb = _load_wave_b()
        home = self.wb.Pad("home", (0.0, -20.0))
        swath = self.wb.Swath((0.0, 0.0), (100.0, 0.0), 100.0)
        self.speed = {"uav-a": 10.0, "uav-b": 10.0}
        self.sorties = [
            self.wb.PackedSortie(
                uav_id="uav-a",
                takeoff_pad_id="home",
                landing_pad_id="home",
                takeoff_xy=home.xy,
                landing_xy=home.xy,
                swaths=[swath],
                flight_time_s=self.wb.sortie_duration_s(home.xy, [swath], home.xy, 10.0),
                start_time_s=0.0,
            ),
            self.wb.PackedSortie(
                uav_id="uav-b",
                takeoff_pad_id="home",
                landing_pad_id="home",
                takeoff_xy=home.xy,
                landing_xy=home.xy,
                swaths=[swath],
                flight_time_s=self.wb.sortie_duration_s(home.xy, [swath], home.xy, 10.0),
                start_time_s=0.0,
            ),
        ]

    def test_conflict_then_clean(self) -> None:
        hits = self.wb.detect_conflicts(self.sorties, self.speed, min_separation_m=20.0)
        self.assertTrue(hits, "identical tracks at t=0 must conflict")
        resolved, n_seen, delay, notes = self.wb.resolve_separation(
            [self.wb._copy_sortie(item) for item in self.sorties],
            self.speed,
            min_separation_m=20.0,
        )
        self.assertGreaterEqual(n_seen, 1)
        self.assertGreater(delay, 0.0)
        after = self.wb.detect_conflicts(resolved, self.speed, min_separation_m=20.0)
        self.assertEqual(after, [])
        starts = {item.uav_id: item.start_time_s for item in resolved}
        self.assertEqual(starts["uav-a"], 0.0)
        self.assertGreater(starts["uav-b"], 0.0)
        self.assertTrue(any("delayed" in line for line in notes))

    def test_zero_buffer_disables_resolver(self) -> None:
        resolved, n_seen, delay, notes = self.wb.resolve_separation(
            self.sorties,
            self.speed,
            min_separation_m=0.0,
        )
        self.assertEqual(n_seen, 0)
        self.assertEqual(delay, 0.0)
        self.assertTrue(any("disabled" in line for line in notes))
        self.assertEqual(resolved[1].start_time_s, 0.0)


class EngineImportTest(unittest.TestCase):
    def test_iso_engine_imports_without_fields2cover(self) -> None:
        path = REPO / "tools" / "f2c_iso" / "fields2cover_engine_iso.py"
        mod = _load_module("fields2cover_engine_iso_under_test", path)
        board = mod.BoardCamera(
            uav_id="b",
            vpp_id="home",
            lat=55.0,
            lon=37.0,
            endurance_s=100.0,
            speed_m_s=12.0,
            spacing_m=20.0,
            h_agl_m=80.0,
            recharge_time_s=15.0,
        )
        self.assertEqual(board.recharge_time_s, 15.0)
        self.assertTrue(hasattr(mod, "CoverageInfeasible"))


if __name__ == "__main__":
    unittest.main()
