#!/usr/bin/python3
"""Configure the owned Docker user service before its first start."""

import json
from pathlib import Path
import subprocess

home = Path.home()
config = home / '.config/docker'
config.mkdir(parents=True, exist_ok=True)
(config / 'daemon.json').write_text(json.dumps({
    'iptables': True, 'ip6tables': True, 'ipv6': False, 'live-restore': False,
    'dns': ['10.0.2.3'], 'firewall-backend': 'iptables',
}))
dropin = home / '.config/systemd/user/docker.service.d'
dropin.mkdir(parents=True, exist_ok=True)
(dropin / 'sandbox.conf').write_text(
    '[Service]\n'
    'Environment="DOCKERD_ROOTLESS_ROOTLESSKIT_NET=slirp4netns"\n'
    'Environment="DOCKERD_ROOTLESS_ROOTLESSKIT_FLAGS=--cidr=10.0.2.0/24"\n'
    'Environment="DOCKERD_ROOTLESS_ROOTLESSKIT_DETACH_NETNS=true"\n'
    'Environment="DOCKERD_ROOTLESS_ROOTLESSKIT_DISABLE_HOST_LOOPBACK=true"\n'
    'ExecStartPost=/usr/bin/python3 /usr/local/share/codex-sandbox/docker-policy.py install\n'
    'TimeoutStartSec=180\n')
subprocess.run(['dockerd-rootless-setuptool.sh', 'install'], check=True, timeout=240)
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=30)
subprocess.run(['systemctl', '--user', 'restart', 'docker'], check=True, timeout=240)
