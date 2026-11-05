#!/usr/bin/env python3
"""Install login services for the existing infrastructure and nested-build VMs."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
CONTROLLERS = {
    "sandbox-host-docker.service": (
        "tools/codex-sandbox/lima/docker_host.py", ".local/state/codex-sandbox-docker/host.json"),
    "agent-build-docker.service": (
        "tools/agent-docker/vm.py", ".local/state/agent-docker/vm.json"),
}


def quote(value, *, command=False):
    """Quote one systemd value, escaping variables only in command arguments."""
    if any(character in value for character in "\n\r\0"):
        raise ValueError("service paths must not contain line breaks or NUL")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def units(root, python, search_path):
    return {
        name: (
            "[Unit]\n"
            f"Description=Start {name.removesuffix('.service')} at login\n\n"
            "[Service]\nType=oneshot\nRemainAfterExit=yes\n"
            "TimeoutStartSec=5min\n"
            # Lima leaves its VM processes running after its CLI exits.
            "KillMode=process\n"
            f"Environment={quote('PATH=' + search_path)}\n"
            f"ExecStart={quote(python, command=True)} {quote(str(root / controller), command=True)} start\n\n"
            "[Install]\nWantedBy=default.target\n"
        )
        for name, (controller, _) in CONTROLLERS.items()
    }


def main(selected=None):
    if sys.platform != "linux":
        raise SystemExit("this installer requires Linux user systemd")
    selected = set(selected or CONTROLLERS)
    unknown = selected - CONTROLLERS.keys()
    if unknown:
        raise ValueError(f"unknown autostart service: {', '.join(sorted(unknown))}")
    provisioned = [name for name, (_, record) in CONTROLLERS.items()
                   if name in selected and (Path.home() / record).is_file()]
    for name in selected - set(provisioned):
        print(f"skipping {name}: VM is not provisioned")
    if not provisioned:
        return
    lima = shutil.which("limactl")
    if lima is None:
        raise SystemExit("limactl is required")
    # Capture Lima's directory: login services do not run shell activation.
    result = subprocess.run([lima, "--version"], check=True, capture_output=True, text=True)
    print(result.stdout.strip())
    search_path = os.pathsep.join((str(Path(lima).parent), "/usr/local/bin", "/usr/bin", "/bin"))
    content = {name: unit for name, unit in
               units(ROOT, str(Path(sys.executable).resolve()), search_path).items()
               if name in provisioned}
    directory = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"
    directory.mkdir(parents=True, exist_ok=True)
    for name, unit in content.items():
        destination = directory / name
        if destination.exists() or destination.is_symlink():
            if destination.read_text() != unit:
                raise SystemExit(f"refusing to replace different service: {destination}")
    with tempfile.TemporaryDirectory(prefix="sandbox-autostart-") as temporary:
        for name, unit in content.items():
            (Path(temporary) / name).write_text(unit)
        subprocess.run(["systemd-analyze", "--user", "verify",
                        *(str(Path(temporary) / name) for name in content)], check=True)
        for name, unit in content.items():
            (directory / name).write_text(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", *content], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", nargs="*", choices=CONTROLLERS)
    main(parser.parse_args().service)
