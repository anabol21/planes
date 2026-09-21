"""Parse the committed ComputeRequest v0 fixture."""

from __future__ import annotations

import unittest

from support import FIXTURE, load_fixture, request_from_fixture

from planes.runtime.types import request_to_dict


class FixtureParseTest(unittest.TestCase):
    def test_fixture_matches_interface_v0(self) -> None:
        raw = load_fixture()
        request = request_from_fixture()
        self.assertEqual(request.contract_version, "v0")
        self.assertEqual(request.job_id, "job_01")
        self.assertEqual(request.scenario, {"id": "scenario_01"})
        self.assertEqual(request.optimization.objective, "min_time")
        self.assertEqual(request.optimization.time_limit_seconds, 30)
        self.assertIsNone(request.optimization.placeholder_outcome)
        self.assertEqual(request.seed, 7)
        self.assertEqual(request_to_dict(request), raw)
        self.assertTrue(FIXTURE.is_file())


if __name__ == "__main__":
    unittest.main()
