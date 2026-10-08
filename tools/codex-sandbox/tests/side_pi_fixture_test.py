#!/usr/bin/env python3
"""Exercise the recording adapter with the production connector and worker."""
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("node"), "requires Node")
class SidePiConnectorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="side-connector-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.socket = self.root / "worker.sock"
        self.environment = os.environ | {
            "HOME": str(self.root),
            "SIDE_PI_RUNTIME": str(self.root),
            "CODEX_SANDBOX_TOOL_SOCKET": str(self.socket),
            "CODEX_SANDBOX_PI_TOOL_MODULE": (HERE / "tool-worker-fixture.mjs").as_uri(),
            "CODEX_SANDBOX_CANCEL_MARKER": str(self.root / "cancelled"),
        }

    def process(self, command):
        child = subprocess.Popen(command, env=self.environment, cwd=self.root,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        self.addCleanup(self.stop, child)
        return child

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream:
                stream.close()

    def worker(self):
        child = self.process(["node", str(HERE.parent / "image/tool-worker.mjs")])
        deadline = time.monotonic() + 5
        while not self.socket.exists():
            self.assertIsNone(child.poll(), "worker exited before creating its socket")
            if time.monotonic() >= deadline:
                self.fail("worker did not start")
            time.sleep(.02)
        return child

    def adapter(self, request):
        child = self.process([sys.executable, str(HERE / "side_pi_fixture.py")])
        data = json.dumps(request).encode() + b"\n"
        child.stdin.write(data)
        child.stdin.flush()
        return child, data

    def assert_recorded(self, data):
        records = list((self.root / "calls").glob("*.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].read_bytes(), data)

    def test_connector_failure_exits_with_caller_stdin_still_open(self):
        child, data = self.adapter({"tool": "read", "params": {"path": "file.txt"}, "model": None})
        # The caller closes stdin only after a terminal result. Do not use
        # communicate(), which would hide the original circular wait by sending EOF.
        child.wait(timeout=5)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn(b"ENOENT", child.stderr.read())
        self.assert_recorded(data)

    def test_success_exits_with_caller_stdin_still_open(self):
        self.worker()
        child, data = self.adapter({"tool": "read", "params": {"path": "file.txt"}, "model": None})
        child.wait(timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr.read())
        self.assertEqual(json.loads(child.stdout.read()), {"kind": "result", "result": {
            "content": [{"type": "text", "text": "guest:file.txt"}],
        }})
        self.assert_recorded(data)

    def test_caller_eof_cancels_pending_guest_work(self):
        self.worker()
        child, data = self.adapter({"tool": "bash", "params": {"command": "sleep"}, "model": None})
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=5), "guest work did not start")
        self.assertEqual(json.loads(child.stdout.readline())["kind"], "update")
        child.stdin.close()
        child.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not (self.root / "cancelled").exists():
            if time.monotonic() >= deadline:
                self.fail("caller EOF did not cancel guest work")
            time.sleep(.02)
        self.assert_recorded(data)


if __name__ == "__main__":
    unittest.main()
