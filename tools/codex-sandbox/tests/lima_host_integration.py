#!/usr/bin/env python3
"""Opt-in disposable provisioning, share, reboot, and network gate."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

import lima_network_integration as network


spec = importlib.util.spec_from_file_location("lima_host", network.ROOT / "lima/host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
IMAGE = "docker.io/library/python@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322"


def interrupt_setup(setup, instance, external, work):
    process = subprocess.Popen([sys.executable, str(network.ROOT / "lima/host.py"),
                                "--state", str(setup.state), "setup", "--instance", instance,
                                "--share-read", str(external), "--share-write", str(work)],
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and process.poll() is None:
            listing = subprocess.run(["ps", "-axo", "pid=,ppid=,command="],
                                     check=True, capture_output=True, text=True, timeout=5)
            rows = [row.split(None, 2) for row in listing.stdout.splitlines()]
            if any(len(row) == 3 and row[1] == str(process.pid) and
                   "limactl start " in row[2] and instance in row[2] for row in rows):
                process.send_signal(signal.SIGTERM)
                if process.wait(timeout=60) != 143:
                    raise AssertionError("setup did not preserve SIGTERM status")
                record = setup.record()
                if record["phase"] == "ready":
                    raise AssertionError("interrupted setup published readiness")
                print("Live setup interruption preserved status 143 and pending ownership.", flush=True)
                return record["generation"]
            time.sleep(0.25)
        raise AssertionError("setup never reached a live startup child")
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main():
    instance = "sandbox-host-test-" + uuid.uuid4().hex[:12]
    marker = uuid.uuid4().hex

    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/" + marker:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(marker.encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Owned fixture: {instance}", flush=True)
    with tempfile.TemporaryDirectory(prefix="sandbox-host-gate-") as temporary:
        root = Path(temporary).resolve()
        work = root / "work"
        external = root / "external metadata"
        work.mkdir()
        external.mkdir()
        (external / "config").write_text("external metadata")
        project = work / "project with spaces"
        (project / "nested").mkdir(parents=True)
        (project / ".git").mkdir()
        (project / ".git/config").write_text("protected metadata")
        (project / ".agents").mkdir()
        (project / ".agents/policy").write_text("hidden policy")
        (work / "sibling").mkdir()
        (project / "live.txt").write_text("first host edit")
        setup = host.Host(root / "state")
        try:
            generation = interrupt_setup(setup, instance, external, work)
            with setup.locked():
                # Installation finished but readiness was never published.
                # Recovery must reuse that generation and installed network.
                with patch.object(setup, "verify", side_effect=InterruptedError("publication interrupted")):
                    try:
                        setup.setup(instance, [external], [work])
                    except InterruptedError:
                        pass
                    else:
                        raise AssertionError("interruption was not exercised")
                pending = setup.record()
                assert pending["phase"] == "installing"
                record = setup.setup(instance, [external], [work])
                assert pending["generation"] == record["generation"]
                assert generation == record["generation"]
                repeated = setup.setup(instance, [external], [work])
                assert repeated == record
            setup.check_bind(project, True)
            setup.check_bind(external)
            (project / "live.txt").write_text("second host edit")
            setup.check_bind(project / "live.txt", True)
            scratch = setup.state / "scratch"
            empty = scratch / "empty"
            empty.mkdir()
            probe = scratch / "mount-probe.py"
            probe.write_bytes(Path(__file__).with_name("lima_mount_guest.py").read_bytes())
            setup.guest(record, "nerdctl", "pull", IMAGE)
            setup.guest(record, "nerdctl", "run", "--rm", "--pull=never", "--network=none",
                        "--cap-drop=ALL", "--security-opt=no-new-privileges",
                        "--mount", f"type=bind,src={work},dst=/src,readonly",
                        "--mount", f"type=bind,src={project},dst=/src/project with spaces,bind-nonrecursive=true",
                        "--mount", f"type=bind,src={project / '.git'},dst=/src/project with spaces/.git,readonly",
                        "--mount", f"type=bind,src={empty},dst=/src/project with spaces/.agents,readonly",
                        "--mount", f"type=bind,src={external},dst=/metadata,readonly",
                        "--mount", f"type=bind,src={probe},dst=/probe.py,readonly",
                        "--workdir", "/src/project with spaces/nested", IMAGE, "python3", "/probe.py")
            assert (project / "written.txt").read_text() == "container edit"
            endpoint = f"http://host.lima.internal:{server.server_port}/{marker}"
            network.install_probe(instance, endpoint, expected_shares=record["shares"])
            setup.verify(record)
            host.command("limactl", "stop", "--tty=false", instance)
            setup.start()
            setup.guest(record, "python3", network.GUEST_PROBE, endpoint)
            setup.verify(record)
            print("Provisioning, live mounts, protected overlays, network policy, and reboot passed.", flush=True)
        finally:
            # This command owns only the randomly named fixture, including a
            # VM left behind by incomplete setup. It never selects a shared VM.
            primary_failure = sys.exc_info()[0] is not None
            try:
                if instance in host.machines():
                    host.command("limactl", "delete", "--force", "--tty=false", instance)
            except (OSError, subprocess.SubprocessError) as error:
                print(f"Owned VM cleanup failed for {instance}: {error}", file=sys.stderr)
                if not primary_failure:
                    raise
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    main()
