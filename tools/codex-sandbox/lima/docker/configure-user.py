#!/usr/bin/python3
"""Configure the owned Docker user service before its first start."""

from pathlib import Path
import subprocess
import shutil

home = Path.home()
dropin = home / '.config/systemd/user/docker.service.d'
dropin.mkdir(parents=True, exist_ok=True)
source = Path('/usr/local/share/codex-sandbox')
shutil.copyfile(source / 'docker-service.conf', dropin / 'sandbox.conf')
for name in ('sandbox.slice', 'sandbox-reclaim.service', 'sandbox-reclaim.timer'):
    shutil.copyfile(source / name, dropin.parent / name)
# Preserve operator enablement on repair. The host enables new installations
# only after their full provisioning audit succeeds.
subprocess.run(['dockerd-rootless-setuptool.sh', 'install'], check=True, timeout=240)
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', '--user', 'restart', 'docker'], check=True, timeout=240)
