#!/usr/bin/python3
"""Install or verify sandbox filtering inside Docker's RootlessKit network."""

import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys

BASE = Path('/usr/local/share/codex-sandbox')
PUBLIC = 'cs-public'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30, **kwargs).stdout


def namespace():
    root = Path(f'/run/user/{os.getuid()}/dockerd-rootless')
    if not (root / 'netns').exists():
        raise ValueError('Docker must use a detached RootlessKit network namespace')
    return ['dockerd-rootless-setuptool.sh', 'nsenter', '--',
            'nsenter', '--net=' + str(root / 'netns'), '--']


def rootless_info():
    connection = http.client.HTTPConnection('localhost', timeout=10)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(10)
    try:
        connection.sock.connect(f'/run/user/{os.getuid()}/dockerd-rootless/api.sock')
        connection.request('GET', '/v1/info')
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('RootlessKit info request failed')
        return json.loads(response.read(65536))
    finally:
        connection.close()


def firewall(install=False):
    import nftables
    nftables.firewall(namespace(), install=install)


def verify(record):
    if os.getuid() == 0 or os.environ.get('SANDBOX_GENERATION') != record['generation']:
        raise ValueError('Docker guest identity changed')
    required = {'nftables.py', 'network.nft', 'docker-daemon.json', 'network-policy.json'}
    if record.get('firewall') != 'nftables' or not required.issubset(record['files']):
        raise ValueError('Docker nftables policy files are not recorded')
    for name, digest in record['files'].items():
        path = BASE / name
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or
                hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError(f'installed Docker policy changed: {name}')
    for unit in ('docker.service', 'docker.socket'):
        properties = run('systemctl', 'show', unit, '--property=ActiveState', '--property=UnitFileState')
        if 'ActiveState=inactive' not in properties or 'UnitFileState=masked' not in properties:
            raise ValueError('rootful Docker is not disabled and masked')
    info = json.loads(run('docker', '--host', f'unix:///run/user/{os.getuid()}/docker.sock',
                          'info', '--format', '{{json .}}'))
    if (info['ServerVersion'] != '29.8.0' or 'name=rootless' not in info['SecurityOptions'] or
            info['LiveRestoreEnabled'] or info['ID'] != record['engine_id']):
        raise ValueError('Docker engine identity or security configuration changed')
    network = json.loads(run('docker', 'network', 'inspect', 'codex-public-only'))[0]
    if (network['Id'] != record['network_id'] or network['Driver'] != 'bridge' or
            network['Internal'] or network['EnableIPv6'] or
            network['Labels'].get('dev.codex.generation') != record['generation'] or
            network['Options'].get('com.docker.network.bridge.name') != PUBLIC or
            network['IPAM']['Config'] != [{'Subnet': '10.254.254.0/24',
                                          'IPRange': '10.254.254.128/25', 'Gateway': '10.254.254.1'}]):
        raise ValueError('Docker public network differs from recorded policy')
    effective = rootless_info()['networkDriver']
    pid = int(run('systemctl', '--user', 'show', 'docker.service', '--property=MainPID', '--value'))
    arguments = (Path('/proc') / str(pid) / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    if (not {'--net=slirp4netns', '--disable-host-loopback', '--cidr=10.0.2.0/24'}.issubset(arguments) or
            effective.get('driver') != 'slirp4netns' or effective.get('dns') != ['10.0.2.3'] or
            effective.get('childIP') != '10.0.2.100'):
        raise ValueError('Docker rootless network driver or resolver changed')
    if record.get('firewall') == 'nftables':
        if arguments[-2:] != ['/usr/bin/dockerd-rootless.sh', '--config-file=' + str(BASE / 'docker-daemon.json')]:
            raise ValueError('Docker is not using the pinned sandbox daemon configuration')
    for index, share in enumerate(record['shares']):
        mounted = json.loads(run('findmnt', '--json', '--target', share['mountPoint'],
                                 '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'))['filesystems']
        if (len(mounted) != 1 or mounted[0]['target'] != share['mountPoint'] or
                mounted[0]['source'] != f'mount{index}' or mounted[0]['fstype'] != 'virtiofs' or
                ('rw' if share['writable'] else 'ro') not in mounted[0]['options'].split(',')):
            raise ValueError('Docker VM share differs from recorded virtiofs mount')
    firewall()


if __name__ == '__main__':
    if sys.argv[1:] == ['install']:
        firewall(install=True)
    elif sys.argv[1:] == ['check']:
        verify(json.load(sys.stdin))
    elif sys.argv[1:] == ['check-bridges']:
        import nftables
        nftables.check_bridges(namespace())
    else:
        raise SystemExit('expected install or check')
