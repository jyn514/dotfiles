"""Check a home-sharing VM without changing its lifecycle or real credentials."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sandbox_runtime import Lima

IMAGE = "docker.io/library/python@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322"


def exercise(state):
    runtime = Lima(state)
    home = Path.home().resolve()
    assert any(share["location"] == str(home) and share["writable"]
               for share in runtime.record["shares"]), "VM is not sharing the host home writable"
    runtime.run(["pull", IMAGE], stdout=subprocess.DEVNULL)
    image = runtime.resolve_image(IMAGE)
    with tempfile.TemporaryDirectory(prefix="home-boundary-", dir=runtime.host.state / "scratch") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        secret = root / "host-only.txt"
        secret.write_text("owned sentinel, not a credential")
        repo = root / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git/config").write_text("protected metadata")
        (repo / "live.txt").write_text("host edit")
        assert runtime.guest(["cat", str(secret)], capture_output=True, text=True).stdout == secret.read_text()
        for uid in (os.getuid(), 0):
            repo.chmod(0o777)
            with runtime.workload(image, "home-boundary-" + secrets.token_hex(6), [
                    "--network", "none", "--user", f"{uid}:{os.getgid()}",
                    "--env", f"HOST_ONLY_FILE={secret}",
                    "--mount", f"type=bind,src={home / 'src'},dst=/src,readonly",
                    "--mount", f"type=bind,src={repo},dst=/src/dotfiles",
                    "--mount", f"type=bind,src={repo / '.git'},dst=/src/dotfiles/.git,readonly",
                    "--mount", f"type=bind,src={ROOT / 'tests/lima_home_guest.py'},dst=/probe.py,readonly",
                    "--entrypoint", "python3"], ["/probe.py"]) as process:
                assert process.wait(timeout=30) == 0
            assert (repo / "written.txt").read_text() == "container edit"
            (repo / "written.txt").unlink()
    print("PASS: VM home access does not grant container home access.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/codex-sandbox-lima")
    exercise(parser.parse_args().state)
