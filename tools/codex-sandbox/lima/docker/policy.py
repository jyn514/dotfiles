#!/usr/bin/python3
"""Install or verify sandbox filtering inside Docker's RootlessKit network."""

import hashlib
import http.client
import json
import os
from pathlib import Path
import shlex
import socket
import stat
import subprocess
import sys

BASE = Path('/usr/local/share/codex-sandbox')
PUBLIC = 'cs-public'
LINK = 'csl+'
EGRESS = 'cse+'


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


def rules(policy, ipv6=False):
    incoming = [['-i', bridge, '-j', 'REJECT'] for bridge in (PUBLIC, LINK)]
    if ipv6:
        return incoming + [['-i', EGRESS, '-j', 'REJECT']], [
            ['-i', bridge, '-j', 'REJECT'] for bridge in (PUBLIC, LINK, EGRESS)]
    # Internal relay traffic is allowed only while bridged, never routed to
    # another link. Interface identity also survives forged source addresses.
    forwarding = [
        ['-i', LINK, '-m', 'physdev', '--physdev-is-bridged', '-j', 'RETURN'],
        ['-i', LINK, '-j', 'REJECT'],
        ['-i', PUBLIC, '-o', PUBLIC, '-j', 'RETURN'],
        ['-i', EGRESS, '-o', PUBLIC, '-j', 'REJECT'],
        ['-i', EGRESS, '-o', LINK, '-j', 'REJECT'],
        ['-i', EGRESS, '-o', EGRESS, '-m', 'physdev', '--physdev-is-bridged', '-j', 'RETURN'],
        ['-i', EGRESS, '-o', EGRESS, '-j', 'REJECT'],
    ]
    for protocol in ('tcp', 'udp'):
        forwarding.append(['-i', PUBLIC, '-d', policy['dns'] + '/32',
                           '-p', protocol, '-m', protocol, '--dport', '53', '-j', 'RETURN'])
    forwarding += [['-i', PUBLIC, '-d', destination, '-j', 'REJECT']
                   for destination in policy['prohibited']]
    return incoming, forwarding


def canonical(rule):
    # iptables-save makes the default REJECT response explicit.
    if '--reject-with' in rule:
        index = rule.index('--reject-with')
        if rule[index + 1] not in ('icmp-port-unreachable', 'icmp6-port-unreachable'):
            raise ValueError('unexpected firewall rejection mode')
        rule = rule[:index] + rule[index + 2:]
    # iptables prints selectors in its own order, e.g. destination before
    # input interface. Compare complete option groups, retaining duplicates.
    groups = []
    index = 0
    while index < len(rule):
        size = 1 if rule[index] == '--physdev-is-bridged' else 2
        groups.append(tuple(rule[index:index + size]))
        index += size
    return tuple(sorted(groups))


def check_chain(prefix, tool, chain, expected):
    actual = [canonical(shlex.split(line)[2:]) for line in
              run(*prefix, tool, '-S', chain).splitlines() if line.startswith('-A ')]
    if actual != [canonical(entry) for entry in expected]:
        raise ValueError(f'{tool} {chain} differs from sandbox policy')


def firewall(install=False):
    policy = json.loads((BASE / 'network-policy.json').read_text())
    if policy['version'] != 2 or policy['ipv6'] != 'disabled':
        raise ValueError('unsupported sandbox policy')
    prefix = namespace()
    for knob in ('bridge-nf-call-iptables', 'bridge-nf-call-ip6tables'):
        if run(*prefix, 'sysctl', '-n', 'net.bridge.' + knob).strip() != '1':
            raise ValueError('bridge filtering must be enabled before Docker starts')
    for tool, ipv6 in (('iptables', False), ('ip6tables', True)):
        incoming, forwarding = rules(policy, ipv6)
        chains = {'CS-INPUT': incoming, 'CS-FORWARD': forwarding}
        if install:
            existing = subprocess.run([*prefix, tool, '-S', 'DOCKER-USER'],
                                      capture_output=True, timeout=30)
            if existing.returncode:
                run(*prefix, tool, '-N', 'DOCKER-USER')
            jumps = run(*prefix, tool, '-S', 'FORWARD').splitlines()
            if '-A FORWARD -j DOCKER-USER' not in jumps:
                run(*prefix, tool, '-I', 'FORWARD', '1', '-j', 'DOCKER-USER')
            content = ['*filter', *[f':{name} - [0:0]' for name in chains]]
            for chain, entries in chains.items():
                content.extend(shlex.join(['-A', chain, *entry]) for entry in entries)
            content.append('COMMIT')
            run(*prefix, tool + '-restore', '--noflush', input='\n'.join(content) + '\n')
            for parent, child in (('INPUT', 'CS-INPUT'), ('DOCKER-USER', 'CS-FORWARD')):
                entries = run(*prefix, tool, '-S', parent).splitlines()
                jump = f'-A {parent} -j {child}'
                if jump in entries:
                    run(*prefix, tool, '-D', parent, '-j', child)
                run(*prefix, tool, '-I', parent, '1', '-j', child)
        for chain, entries in chains.items():
            check_chain(prefix, tool, chain, entries)
        for parent, child in (('INPUT', 'CS-INPUT'), ('DOCKER-USER', 'CS-FORWARD'),
                              ('FORWARD', 'DOCKER-USER')):
            entries = [line for line in run(*prefix, tool, '-S', parent).splitlines()
                       if line.startswith('-A ')]
            if not entries or entries[0] != f'-A {parent} -j {child}':
                raise ValueError('sandbox firewall jump is not first')


def verify(record):
    if os.getuid() == 0 or os.environ.get('SANDBOX_GENERATION') != record['generation']:
        raise ValueError('Docker guest identity changed')
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
    else:
        raise SystemExit('expected install or check')
