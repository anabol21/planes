"""Isolated client keeps a clean env and honors embed/worker paths."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def _load_client():
    import importlib.util

    path = REPO / "tools" / "f2c_iso" / "f2c_isolated_client.py"
    spec = importlib.util.spec_from_file_location("f2c_isolated_client_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class IsolatedClientTest(unittest.TestCase):
    def test_clean_env_drops_pythonpath_and_forces_no_user_site(self) -> None:
        client = _load_client()
        dirty = {
            "PYTHONPATH": "/opt/planes/src/planes/model/itog_model/mvp_optimizator/src",
            "PYTHONHOME": "/opt/bad",
            "PYTHONSTARTUP": "/tmp/startup.py",
            "PYTHONUSERBASE": "/tmp/user",
            "HOME": "/home/planes",
            "LANG": "en_US.UTF-8",
        }
        cleaned = client.clean_env(dirty)
        self.assertNotIn("PYTHONPATH", cleaned)
        self.assertNotIn("PYTHONHOME", cleaned)
        self.assertNotIn("PYTHONSTARTUP", cleaned)
        self.assertNotIn("PYTHONUSERBASE", cleaned)
        self.assertEqual(cleaned["PYTHONNOUSERSITE"], "1")
        self.assertEqual(cleaned["HOME"], "/home/planes")
        self.assertNotIn("mvp_optimizator", " ".join(cleaned.values()))

    def test_worker_env_aliases(self) -> None:
        client = _load_client()
        previous = {
            key: os.environ.get(key)
            for key in ("PLANES_F2C_WORKER", "F2C_ISO_WORKER")
        }
        try:
            os.environ.pop("PLANES_F2C_WORKER", None)
            os.environ.pop("F2C_ISO_WORKER", None)
            self.assertEqual(
                client.default_worker_path(),
                REPO / "tools" / "f2c_iso" / "f2c_isolated_worker.py",
            )
            os.environ["F2C_ISO_WORKER"] = "/tmp/alias-worker.py"
            self.assertEqual(client.default_worker_path(), Path("/tmp/alias-worker.py"))
            os.environ["PLANES_F2C_WORKER"] = "/tmp/planes-worker.py"
            self.assertEqual(client.default_worker_path(), Path("/tmp/planes-worker.py"))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_solve_uses_embed_python_and_clean_env(self) -> None:
        client = _load_client()
        with tempfile.TemporaryDirectory() as tmp:
            worker = Path(tmp) / "f2c_isolated_worker.py"
            worker.write_text("# stub\n", encoding="utf-8")
            embed = Path(tmp) / "python"
            embed.write_text("", encoding="utf-8")
            embed.chmod(0o755)
            captured: dict[str, object] = {}

            class FakeProc:
                returncode = 0
                stdout = json.dumps({"outcome": "feasible", "isolation": {"mvp_on_path": False}}).encode()
                stderr = b""

            def fake_run(argv, **kwargs):
                captured["argv"] = argv
                captured["env"] = kwargs["env"]
                captured["cwd"] = kwargs["cwd"]
                return FakeProc()

            with patch.object(client.subprocess, "run", fake_run):
                resp = client.solve({"job_id": "t"}, worker=worker, python_bin=embed, timeout_s=8)
            self.assertEqual(resp["outcome"], "feasible")
            self.assertEqual(captured["argv"], [str(embed), str(worker)])
            env = captured["env"]
            assert isinstance(env, dict)
            self.assertNotIn("PYTHONPATH", env)
            self.assertEqual(env["PYTHONNOUSERSITE"], "1")
            self.assertEqual(captured["cwd"], tmp)


if __name__ == "__main__":
    unittest.main()
