"""Check the real interactive wrapper's successful directory handoff boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_pi_owner import HostPiOwner

FIXTURE = Path(__file__).with_name("host_pi_owner_fixture.py")
LAUNCHER_FIXTURE = Path(__file__).with_name("fixtures") / "host_pi_cd_launcher.py"


class HostPiHandoffTest(unittest.TestCase):
    def test_successful_cd_passes_actual_origin_and_saved_session_to_destination_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / "origin"
            destination = root / "destination"
            origin.mkdir()
            destination.mkdir()
            session = origin / "session.jsonl"
            session.write_text('{}\n')
            receipt = root / "receipt.json"
            launcher = root / "launcher"
            subprocess.run(["cp", str(LAUNCHER_FIXTURE), str(launcher)], check=True)
            subprocess.run(["cmp", str(LAUNCHER_FIXTURE), str(launcher)], check=True)
            launcher.chmod(0o700)
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("CODEX_SANDBOX_")}
            environment.update(CODEX_SANDBOX_CD_VALIDATE=str(launcher),
                               HOST_PI_HANDOFF_RECEIPT=str(receipt),
                               CODEX_SANDBOX_PREVIOUS_CWD="/older/historical-origin")
            owner = HostPiOwner(FIXTURE, ["--session", str(session)], origin, environment, timeout=5)
            owner.start()
            spec = owner.launch_spec(owner.original)
            process = None
            try:
                process = subprocess.Popen(spec["argv"], cwd=spec["cwd"], env=spec["env"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                deadline = time.monotonic() + 6
                while not session.with_suffix(".ready").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail("source Pi did not become ready")
                    time.sleep(.01)
                session.with_suffix(".handoff").write_text(json.dumps({
                    "destination": str(destination), "session": str(session),
                }))
                with owner.lock:
                    self.assertTrue(owner.lock.wait_for(lambda: owner.stopping, timeout=6),
                                    "source attachment did not release")
                owner.finish(True)
                stdout, stderr = process.communicate(timeout=6)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout, "")
                result = json.loads(receipt.read_text())
                self.assertEqual(result["cwd"], str(destination))
                self.assertEqual(result["previous_cwd"], str(origin),
                                 "each handoff replaces the older historical origin")
                arguments = result["arguments"]
                self.assertEqual(arguments[arguments.index("--fork") + 1], str(session))
                self.assertIn("--session-id", arguments)
            finally:
                owner.finish(True)
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=6)


if __name__ == "__main__":
    unittest.main()
