"""CLI outcomes. The shared fixture scenario is not Grisha's InputData.

Crash, invalid stdout, and sleep still use ``PLANES_SOLVER_ARGV`` to reach
the placeholder module. That module is not the product path.
"""

from __future__ import annotations

import sys
import unittest

from support import load_fixture, run_cli

_PLACEHOLDER = f"{sys.executable} -m planes.runtime.placeholder"


class OutcomeTest(unittest.TestCase):
    def test_fixture_file_reports_solver_error(self) -> None:
        from support import FIXTURE

        body = run_cli(None, "5", request_path=str(FIXTURE))
        self.assertEqual(body["outcome"], "error")
        self.assertEqual(body["contract_version"], "v0")
        self.assertEqual(body["job_id"], "job_01")
        self.assertEqual(body["solver_report"]["objective"], "min_time")
        self.assertEqual(body["solver_report"]["seed"], 7)
        self.assertNotIn("mission_plan", body)
        self.assertTrue(
            any("solver failed before producing a result" in item for item in body["solver_report"]["limitations"])
        )
        self.assertNotEqual(body["outcome"], "feasible")

    def test_invalid_stdout_is_error(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "invalid"
        body = run_cli(payload, "5", extra_env={"PLANES_SOLVER_ARGV": _PLACEHOLDER})
        self.assertEqual(body["outcome"], "error")
        self.assertNotIn("mission_plan", body)
        self.assertTrue(any("stdout" in item for item in body["solver_report"]["limitations"]))

    def test_crash_is_error(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "crash"
        body = run_cli(payload, "5", extra_env={"PLANES_SOLVER_ARGV": _PLACEHOLDER})
        self.assertEqual(body["outcome"], "error")
        self.assertNotIn("mission_plan", body)
        self.assertTrue(any("status" in item for item in body["solver_report"]["limitations"]))

    def test_sleep_is_timed_out(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "sleep"
        payload["optimization"]["time_limit_seconds"] = 30
        body = run_cli(payload, "0.5", extra_env={"PLANES_SOLVER_ARGV": _PLACEHOLDER})
        self.assertEqual(body["outcome"], "timed_out")
        self.assertNotIn("mission_plan", body)
        self.assertLess(body["solver_report"]["runtime_seconds"], 4)

    def test_request_that_is_not_json_is_error(self) -> None:
        import json
        import os
        import subprocess
        import sys

        from support import SRC, TOKEN

        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        env["COMPUTE_TOKEN"] = TOKEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "planes.runtime.cli",
                "solve",
                "--request",
                "-",
                "--timeout-seconds",
                "1",
            ],
            input=b"not-json",
            capture_output=True,
            env=env,
            timeout=8,
            check=False,
        )
        body = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(body["outcome"], "error")
        self.assertNotIn(TOKEN, proc.stdout.decode("utf-8"))
        self.assertNotIn(TOKEN, proc.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
