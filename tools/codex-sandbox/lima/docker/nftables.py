"""Own sandbox nftables tables without modifying Docker's iptables chains."""

import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

BASE = Path(__file__).resolve().parent
KNOBS = ('net.bridge.bridge-nf-call-iptables', 'net.bridge.bridge-nf-call-ip6tables')


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.strip()}')
    return result.stdout


def source(policy):
    if policy['version'] != 2 or policy['ipv6'] != 'disabled':
        raise ValueError('unsupported sandbox policy')
    addresses = ', '.join(str(ipaddress.IPv4Network(value)) for value in policy['prohibited'])
    dns = str(ipaddress.IPv4Address(policy['dns']))
    return (BASE / 'network.nft').read_text().replace('@PROHIBITED@', addresses).replace('@DNS@', dns)


def canonical(listing):
    """Preserve complete expressions and ordering, excluding only kernel handles."""
    objects = []
    for entry in json.loads(listing)['nftables']:
        if 'metainfo' in entry:
            continue
        kind, value = next(iter(entry.items()))
        if (value.get('family') not in ('inet', 'bridge') or
                value.get('table', value.get('name')) != 'codex_sandbox'):
            continue
        objects.append({kind: {key: item for key, item in value.items() if key != 'handle'}})
    # Tables can appear in a different order after a restart; order within each
    # family, including every rule and expression, remains significant.
    return sorted(objects, key=lambda entry: next(iter(entry.values()))['family'])


def dump(prefix):
    return canonical(run(*prefix, 'nft', '--stateless', '--json', 'list', 'ruleset'))


def check_bridges(prefix):
    if run(*prefix, 'sysctl', '-n', *KNOBS).split() != ['0', '0']:
        raise ValueError('Docker re-enabled bridge IP traversal; sandbox network is not ready')


def check_networks():
    client = ['docker', '--host', f'unix:///run/user/{os.getuid()}/docker.sock']
    ids = run(*client, 'network', 'ls', '--filter', 'driver=bridge', '--quiet').split()
    if ids:
        for network in json.loads(run(*client, 'network', 'inspect', *ids)):
            if network['Options'].get('com.docker.network.bridge.enable_icc', 'true') != 'true':
                raise ValueError('ICC-disabled Docker networks are incompatible with sandbox nftables')


def reference(prefix, content):
    origin = run(*prefix, 'readlink', '/proc/self/ns/net').strip()

    def interrupted(signum, _frame):
        # selectors treats InterruptedError as a retryable interrupted syscall.
        raise RuntimeError(f'nftables verification interrupted by signal {signum}')

    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    handlers = {signum: signal.signal(signum, interrupted) for signum in signals}
    process = None
    try:
        process = subprocess.Popen([*prefix, 'unshare', '--net', '/usr/bin/python3', str(Path(__file__).resolve()),
                                    'reference', origin], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        output, error = process.communicate(content, timeout=20)
        if process.returncode:
            raise ValueError('nftables reference compilation failed: ' + error.strip())
        return json.loads(output)
    finally:
        for signum in signals:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if process is not None:
                # The compiler can have an nft child after its wrapper exits.
                # This group owns only a fresh namespace, never the live daemon.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=5)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)


def firewall(prefix, *, install=False):
    content = source(json.loads((BASE / 'network-policy.json').read_text()))
    check_networks()
    if install:
        # Atomic replacement precedes disabling IP traversal. Workloads have no
        # restart policy, and systemd cannot publish readiness until this returns.
        run(*prefix, 'nft', '-f', '-', input=content)
        run(*prefix, 'sysctl', '-qw', *[name + '=0' for name in KNOBS])
    check_bridges(prefix)
    expected = reference(prefix, content)
    if dump(prefix) != expected:
        raise ValueError('installed nftables tables differ from sandbox policy')


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'reference':
        raise SystemExit('reference requires a fresh network namespace')
    if os.readlink('/proc/self/ns/net') == sys.argv[2]:
        raise SystemExit('refusing to compile policy in the live network namespace')
    run('nft', '-f', '-', input=sys.stdin.read())
    print(json.dumps(dump([])))
