"""Listener routes: health, authorized solve, and rejected credentials."""

from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.request

from support import TOKEN, env_vars, load_fixture, post_json, vps_listener

from planes.runtime.lock import JobLock


class HttpListenerTest(unittest.TestCase):
    def test_health_has_contract_version_and_no_job(self) -> None:
        with vps_listener():
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
                raw = response.read()
                self.assertEqual(response.status, 200)
            body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body, {"status": "live", "contract_version": "v0"})
        self.assertNotIn("job_id", body)
        self.assertNotIn(TOKEN, raw.decode("utf-8"))

    def test_solve_returns_compute_response(self) -> None:
        with vps_listener():
            status, body = post_json(load_fixture(), TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "error")
        self.assertEqual(body["job_id"], "job_01")
        self.assertEqual(body["contract_version"], "v0")
        self.assertNotIn("mission_plan", body)
        self.assertTrue(
            any("solver body is not implemented" in item for item in body["solver_report"]["limitations"])
        )
        self.assertNotIn(TOKEN, str(body))

    def test_unimplemented_body_is_http_200_not_infeasible(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "infeasible"
        with vps_listener():
            status, body = post_json(payload, TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "error")
        self.assertNotEqual(body["outcome"], "infeasible")
        self.assertNotIn("mission_plan", body)

    def test_missing_token_is_401(self) -> None:
        with vps_listener():
            status, body = post_json(load_fixture(), None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")
        self.assertNotIn("infeasible", str(body))

    def test_wrong_token_is_401(self) -> None:
        with vps_listener():
            status, body = post_json(load_fixture(), "not-the-token")
        self.assertEqual(status, 401)
        self.assertNotIn("infeasible", str(body))

    def test_busy_lock_is_503(self) -> None:
        with vps_listener() as lock_path:
            lock = JobLock(lock_path)
            self.assertTrue(lock.try_acquire())
            try:
                status, body = post_json(load_fixture(), TOKEN)
            finally:
                lock.release()
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "busy")
        self.assertNotIn("infeasible", str(body))

    def test_time_limit_is_the_cli_timeout(self) -> None:
        payload = load_fixture()
        payload["optimization"]["placeholder_outcome"] = "sleep"
        payload["optimization"]["time_limit_seconds"] = 0.5
        started = time.monotonic()
        with env_vars(PLANES_SOLVER_ARGV=f"{sys.executable} -m planes.runtime.placeholder"):
            with vps_listener():
                status, body = post_json(payload, TOKEN)
        elapsed = time.monotonic() - started
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "timed_out")
        self.assertLess(elapsed, 4)


if __name__ == "__main__":
    unittest.main()
