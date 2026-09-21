"""RuntimeEngineAdapter talks only to the compute listener."""

from __future__ import annotations

import inspect
import socket
import threading
import time
import unittest

from support import TOKEN, env_vars, request_from_fixture, vps_listener

from planes.runtime.adapter import RuntimeEngineAdapter
import planes.runtime.adapter as adapter_module


class AdapterTest(unittest.TestCase):
    def test_module_does_not_spawn_a_solver(self) -> None:
        source = inspect.getsource(adapter_module)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("RUNTIME_MODE", source)
        self.assertNotIn("planes.runtime.cli", source)

    def test_missing_configuration_is_error(self) -> None:
        with env_vars(COMPUTE_HOST=None, COMPUTE_TOKEN=None, COMPUTE_TIMEOUT_SECONDS=None):
            response = RuntimeEngineAdapter().solve(request_from_fixture())
        self.assertEqual(response.outcome, "error")
        self.assertIsNone(response.mission_plan)
        self.assertTrue(any("Missing compute configuration" in item for item in response.solver_report.limitations))

    def test_unreachable_listener_is_error(self) -> None:
        with env_vars(
            COMPUTE_HOST="127.0.0.1",
            COMPUTE_TOKEN=TOKEN,
            COMPUTE_TIMEOUT_SECONDS="2",
        ):
            response = RuntimeEngineAdapter().solve(request_from_fixture())
        self.assertEqual(response.outcome, "error")
        self.assertTrue(any("unreachable" in item for item in response.solver_report.limitations))
        self.assertNotIn("infeasible", " ".join(response.solver_report.limitations))
        self.assertNotIn(TOKEN, " ".join(response.solver_report.limitations))

    def test_posts_request_to_listener(self) -> None:
        with vps_listener(TOKEN):
            with env_vars(
                COMPUTE_HOST="127.0.0.1",
                COMPUTE_TOKEN=TOKEN,
                COMPUTE_TIMEOUT_SECONDS="5",
            ):
                response = RuntimeEngineAdapter().solve(request_from_fixture())
        self.assertEqual(response.outcome, "error")
        self.assertEqual(response.job_id, "job_01")
        self.assertEqual(response.contract_version, "v0")
        self.assertIsNone(response.mission_plan)
        self.assertEqual(response.solver_report.seed, 7)
        self.assertIn("solver body is not implemented", response.solver_report.limitations)

    def test_listener_401_is_error(self) -> None:
        with vps_listener(TOKEN):
            with env_vars(
                COMPUTE_HOST="127.0.0.1",
                COMPUTE_TOKEN="wrong-token",
                COMPUTE_TIMEOUT_SECONDS="5",
            ):
                response = RuntimeEngineAdapter().solve(request_from_fixture())
        self.assertEqual(response.outcome, "error")
        self.assertTrue(any("401" in item for item in response.solver_report.limitations))
        self.assertNotIn("infeasible", " ".join(response.solver_report.limitations))

    def test_listener_503_is_error(self) -> None:
        from planes.runtime.lock import JobLock

        with vps_listener(TOKEN) as lock_path:
            lock = JobLock(lock_path)
            self.assertTrue(lock.try_acquire())
            try:
                with env_vars(
                    COMPUTE_HOST="127.0.0.1",
                    COMPUTE_TOKEN=TOKEN,
                    COMPUTE_TIMEOUT_SECONDS="5",
                ):
                    response = RuntimeEngineAdapter().solve(request_from_fixture())
            finally:
                lock.release()
        self.assertEqual(response.outcome, "error")
        self.assertTrue(any("503" in item for item in response.solver_report.limitations))
        self.assertNotIn("infeasible", " ".join(response.solver_report.limitations))

    def test_client_timeout_is_timed_out(self) -> None:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 8080))
        sock.listen(1)
        started = threading.Event()
        held: list[socket.socket] = []

        def _accept() -> None:
            started.set()
            try:
                conn, _addr = sock.accept()
            except OSError:
                return
            held.append(conn)
            try:
                conn.recv(1)
            except OSError:
                return

        thread = threading.Thread(target=_accept, daemon=True)
        thread.start()
        self.assertTrue(started.wait(1))
        try:
            with env_vars(
                COMPUTE_HOST="127.0.0.1",
                COMPUTE_TOKEN=TOKEN,
                COMPUTE_TIMEOUT_SECONDS="0.4",
            ):
                begun = time.monotonic()
                response = RuntimeEngineAdapter().solve(request_from_fixture())
                elapsed = time.monotonic() - begun
        finally:
            for conn in held:
                conn.close()
            sock.close()
            thread.join(timeout=2)
        self.assertEqual(response.outcome, "timed_out")
        self.assertLess(elapsed, 3)
        self.assertNotIn("infeasible", " ".join(response.solver_report.limitations))


if __name__ == "__main__":
    unittest.main()
