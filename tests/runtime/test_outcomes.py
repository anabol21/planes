"""Map placeholder results through the CLI the VPS listener spawns."""

from __future__ import annotations

import unittest

from support import load_fixture, run_cli


class OutcomeTest(unittest.TestCase):
    def test_fixture_file_is_feasible(self) -> None:
        from support import FIXTURE

        body = run_cli(None, "5", request_path=str(FIXTURE))
        self.assertEqual(body["outcome"], "feasible")
        self.assertEqual(body["contract_version"], "v0")
        self.assertEqual(body["job_id"], "job_01")
        self.assertEqual(body["solver_report"]["method"], "placeholder")
        self.assertEqual(body["solver_report"]["objective"], "min_time")
        self.assertEqual(body["solver_report"]["seed"], 7)
        self.assertGreaterEqual(body["solver_report"]["runtime_seconds"], 0)
        self.assertIn("mission_plan", body)
        self.assertEqual(body["mission_plan"]["kind"], "placeholder")
        self.assertTrue(any(item["kind"] == "log" for item in body["artifacts"]))
        self.assertTrue(
            any("not globally optimal" in item for item in body["solver_report"]["limitations"])
        )

    def test_infeasible_is_a_solver_outcome(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "infeasible"
        body = run_cli(payload, "5")
        self.assertEqual(body["outcome"], "infeasible")
        self.assertNotIn("mission_plan", body)
        self.assertEqual(body["solver_report"]["seed"], 7)
        self.assertNotEqual(body["outcome"], "error")

    def test_invalid_stdout_is_error(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "invalid"
        body = run_cli(payload, "5")
        self.assertEqual(body["outcome"], "error")
        self.assertNotIn("mission_plan", body)
        self.assertTrue(any("stdout" in item for item in body["solver_report"]["limitations"]))

    def test_crash_is_error(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "crash"
        body = run_cli(payload, "5")
        self.assertEqual(body["outcome"], "error")
        self.assertNotIn("mission_plan", body)
        self.assertTrue(any("status" in item for item in body["solver_report"]["limitations"]))

    def test_sleep_is_timed_out(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "sleep"
        payload["optimization"]["time_limit_seconds"] = 30
        body = run_cli(payload, "0.5")
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
