#!/usr/bin/python3
"""Provision the pinned Docker packages in an owned Ubuntu arm64 VM."""

import hashlib
import os
from pathlib import Path
import platform
import subprocess
from urllib.request import urlopen

VERSION = '5:29.8.0-1~ubuntu.24.04~noble'
KEY_SHA256 = '1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570'


def run(*args):
    subprocess.run(args, check=True, timeout=900,
                   env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})


def main():
    if os.getuid() != 0 or platform.machine() != 'aarch64':
        raise ValueError('Docker setup requires the owned arm64 guest root')
    with urlopen('https://download.docker.com/linux/ubuntu/gpg', timeout=30) as response:
        key = response.read(32768)
    if hashlib.sha256(key).hexdigest() != KEY_SHA256:
        raise ValueError('Docker apt signing key changed')
    Path('/etc/apt/keyrings').mkdir(exist_ok=True)
    Path('/etc/apt/keyrings/docker.asc').write_bytes(key)
    Path('/etc/apt/sources.list.d/docker.list').write_text(
        'deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] '
        'https://download.docker.com/linux/ubuntu noble stable\n')
    # Mask before package installation: package postinst may start rootful Docker.
    run('systemctl', 'mask', 'docker.service', 'docker.socket')
    run('apt-get', 'update')
    run('apt-get', 'install', '-y', 'uidmap', 'dbus-user-session', 'iptables',
        'docker-ce=' + VERSION, 'docker-ce-cli=' + VERSION,
        'docker-ce-rootless-extras=' + VERSION,
        'containerd.io=2.3.5-1~ubuntu.24.04~noble',
        'docker-buildx-plugin=0.37.0-1~ubuntu.24.04~noble')
    run('systemctl', 'disable', '--now', 'docker.service', 'docker.socket')
    run('systemctl', 'mask', 'docker.service', 'docker.socket')
    Path('/etc/modules-load.d/codex-sandbox.conf').write_text('br_netfilter\n')
    Path('/etc/sysctl.d/90-codex-sandbox.conf').write_text(
        'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\n')
    run('modprobe', 'br_netfilter')
    run('sysctl', '--system')


if __name__ == '__main__':
    main()
