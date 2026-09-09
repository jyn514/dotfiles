"""Compare firewall candidates in fresh Linux network namespaces, without Docker.

Run as guest root. The outer process creates the test namespace; all bridges,
routes, sysctls and rules belong to it. Peer namespaces live only as child PIDs.
"""

from contextlib import ExitStack
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from network_policy import policy_bytes
from docker_runtime import stop_build
from lima.docker.nftables import source


def ignore_cancellation():
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, signal.SIG_IGN)


def cancelled(signum, _frame):
    ignore_cancellation()
    raise SystemExit(128 + signum)


def handle_cancellation():
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, cancelled)


def run(*command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, timeout=20, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed ({result.returncode}): {result.stderr.strip()}')
    return result.stdout


def ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(10) or process.stdout.readline().strip() != 'ready':
            raise RuntimeError('namespace peer did not become ready')


def stop(process):
    if process.stdin:
        process.stdin.close()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    if process.stdout:
        process.stdout.close()


def peer(stack, bridge, address, index):
    process = subprocess.Popen(['unshare', '--net', sys.executable, str(HERE / 'packet.py'), 'hold'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stack.callback(stop, process)
    ready(process)
    prefix = ['nsenter', '--net=' + f'/proc/{process.pid}/ns/net', '--']
    host, guest = f'v{index}h', f'v{index}g'
    run('ip', 'link', 'add', host, 'type', 'veth', 'peer', 'name', guest)
    run('ip', 'link', 'set', guest, 'netns', str(process.pid))
    run('ip', 'link', 'set', host, 'master', bridge)
    run('ip', 'link', 'set', host, 'up')
    run(*prefix, 'ip', 'link', 'set', guest, 'name', 'eth0')
    run(*prefix, 'ip', 'link', 'set', 'lo', 'up')
    run(*prefix, 'ip', 'addr', 'add', address, 'dev', 'eth0')
    run(*prefix, 'ip', 'link', 'set', 'eth0', 'up')
    octets = address.split('/')[0].split('.')
    ipv6 = f'fd00:{octets[1]}:{octets[2]}::{octets[3]}'
    gateway6 = f'fd00:{octets[1]}:{octets[2]}::1'
    run(*prefix, 'ip', '-6', 'addr', 'add', ipv6 + '/64', 'dev', 'eth0', 'nodad')
    run(*prefix, 'ip', '-6', 'route', 'add', 'default', 'via', gateway6)
    gateway = str(ipaddress.ip_interface(address).network.network_address + 1)
    run(*prefix, 'ip', 'route', 'add', 'default', 'via', gateway)
    run(*prefix, 'sysctl', '-qw', 'net.ipv4.conf.all.rp_filter=0', 'net.ipv4.conf.eth0.rp_filter=0')
    mac = json.loads(run('ip', '-j', 'link', 'show', bridge))[0]['address']
    peer_mac = json.loads(run(*prefix, 'ip', '-j', 'link', 'show', 'eth0'))[0]['address']
    return {'prefix': prefix, 'ip': address.split('/')[0], 'ipv6': ipv6,
            'gateway': gateway, 'gateway6': gateway6,
            'gateway_mac': mac, 'mac': peer_mac}


def probe(sender, receiver, address, *, port=18765, mac=None, source=None):
    command = [sys.executable, str(HERE / 'packet.py')]
    listener = subprocess.Popen([*receiver['prefix'], *command, 'listen', '--port', str(port),
                                 '--address', '::' if ':' in address else '0.0.0.0'],
                                stdout=subprocess.PIPE, text=True)
    try:
        ready(listener)
        arguments = ['send', '--address', address, '--port', str(port)]
        if mac:
            arguments += ['--mac', mac]
        if source:
            arguments += ['--source', source]
        run(*sender['prefix'], *command, *arguments)
        return listener.wait(timeout=3) == 0
    finally:
        stop(listener)


def old_policy(policy):
    spec = importlib.util.spec_from_file_location('old_policy', HERE / 'legacy_policy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for tool, ipv6 in (('iptables', False), ('ip6tables', True)):
        incoming, forwarding = module.rules(policy, ipv6)
        for chain, entries in (('INPUT', incoming), ('FORWARD', forwarding)):
            for entry in entries:
                run(tool, '-A', chain, *entry)


def candidate(policy, name='policy.nft'):
    if name == 'policy.nft':
        return source(policy)
    # Addresses come from the same policy bytes as provisioning; validate before
    # substituting into the separate nft language source.
    networks = ', '.join(str(ipaddress.IPv4Network(value)) for value in policy['prohibited'])
    dns = str(ipaddress.IPv4Address(policy['dns']))
    return (HERE / name).read_text().replace('@PROHIBITED@', networks).replace('@DNS@', dns)


def owned_tables():
    """Keep kernel expressions; discard only unstable object handles and counters."""
    objects = []
    for family in ('inet', 'bridge'):
        listing = json.loads(run('nft', '--stateless', '--json', 'list', 'table', family, 'codex_sandbox'))
        for entry in listing['nftables']:
            if 'metainfo' in entry:
                continue
            kind, value = next(iter(entry.items()))
            objects.append({kind: {key: item for key, item in value.items() if key != 'handle'}})
    return objects


def inside(origin):
    current = os.readlink('/proc/self/ns/net')
    if current == origin or current == os.readlink('/proc/1/ns/net'):
        raise RuntimeError('refusing to change rules in the caller or VM network namespace')
    run('sysctl', '-qw', 'net.ipv4.ip_forward=1', 'net.ipv4.conf.all.rp_filter=0',
        'net.ipv6.conf.all.forwarding=1',
        'net.ipv4.conf.default.rp_filter=0', 'net.ipv4.conf.all.send_redirects=0',
        'net.ipv4.conf.default.send_redirects=0',
        'net.bridge.bridge-nf-call-iptables=1', 'net.bridge.bridge-nf-call-ip6tables=1')
    run('ip', 'link', 'set', 'lo', 'up')
    definitions = [('cs-public', '10.254.254.1/24'), ('csl-one', '172.20.0.1/24'),
                   ('csl-two', '172.21.0.1/24'), ('cse-one', '172.22.0.1/24'),
                   ('cse-two', '172.23.0.1/24'), ('outside', '198.51.100.1/24')]
    for name, address in definitions:
        run('ip', 'link', 'add', name, 'type', 'bridge')
        run('ip', 'addr', 'add', address, 'dev', name)
        octets = address.split('/')[0].split('.')
        run('ip', '-6', 'addr', 'add', f'fd00:{octets[1]}:{octets[2]}::1/64',
            'dev', name, 'nodad')
        run('ip', 'link', 'set', name, 'up')
    with ExitStack() as stack:
        public = peer(stack, 'cs-public', '10.254.254.2/24', 1)
        link = peer(stack, 'csl-one', '172.20.0.2/24', 2)
        linked = peer(stack, 'csl-one', '172.20.0.3/24', 3)
        other = peer(stack, 'csl-two', '172.21.0.2/24', 4)
        egress = peer(stack, 'cse-one', '172.22.0.2/24', 5)
        egress_peer = peer(stack, 'cse-one', '172.22.0.3/24', 6)
        egress_other = peer(stack, 'cse-two', '172.23.0.2/24', 7)
        outside = peer(stack, 'outside', '198.51.100.2/24', 8)
        # Addresses are local fixtures, not internet destinations.
        for address in ('1.1.1.1', '10.0.2.3', '192.168.99.1'):
            run(*outside['prefix'], 'ip', 'addr', 'add', address + '/32', 'dev', 'lo')
            run('ip', 'route', 'add', address + '/32', 'via', outside['ip'])
        host = {'prefix': []}
        cases = [
            ('public internet', public, outside, '1.1.1.1', True, {}),
            ('public DNS', public, outside, '10.0.2.3', True, {'port': 53}),
            ('DNS non-DNS port', public, outside, '10.0.2.3', False, {}),
            ('private destination', public, outside, '192.168.99.1', False, {}),
            ('public gateway', public, host, public['gateway'], False, {}),
            ('internal gateway', link, host, link['gateway'], False, {}),
            ('same link', link, linked, linked['ip'], True, {}),
            ('other link', link, other, other['ip'], False, {}),
            ('link internet', link, outside, '1.1.1.1', False, {}),
            ('egress private', egress, outside, '192.168.99.1', True, {}),
            ('egress gateway', egress, host, egress['gateway'], True, {}),
            ('egress same link', egress, egress_peer, egress_peer['ip'], True, {}),
            ('egress other link', egress, egress_other, egress_other['ip'], False, {}),
            ('egress to internal', egress, linked, linked['ip'], False, {}),
            ('egress to public', egress, public, public['ip'], False, {}),
            ('forged source on public', public, outside, '192.168.99.1', False,
             {'mac': public['gateway_mac']}),
            ('forged bridged link', link, linked, linked['ip'], True, {'mac': linked['mac']}),
            ('forged routed same link', link, linked, linked['ip'], False, {'mac': link['gateway_mac']}),
            ('forged routed other link', link, other, other['ip'], False, {'mac': link['gateway_mac']}),
            ('forged bridged egress', egress, egress_peer, egress_peer['ip'], True, {'mac': egress_peer['mac']}),
            ('forged routed same egress', egress, egress_peer, egress_peer['ip'], False,
             {'mac': egress['gateway_mac']}),
            ('forged routed other egress', egress, egress_other, egress_other['ip'], False,
             {'mac': egress['gateway_mac']}),
            ('IPv6 public gateway', public, host, public['gateway6'], False, {}),
            ('IPv6 internal link', link, linked, linked['ipv6'], False, {}),
            ('IPv6 egress link', egress, egress_peer, egress_peer['ipv6'], False, {}),
            ('IPv6 egress gateway', egress, host, egress['gateway6'], False, {}),
        ]
        # Keep IPv6 controls independent of neighbor-discovery timeouts once
        # policy intentionally blocks IPv6, including its discovery packets.
        for sender in (public, link, egress):
            run(*sender['prefix'], 'ip', '-6', 'neigh', 'replace', sender['gateway6'],
                'lladdr', sender['gateway_mac'], 'nud', 'permanent', 'dev', 'eth0')
        for sender, receiver in ((link, linked), (egress, egress_peer)):
            run(*sender['prefix'], 'ip', '-6', 'neigh', 'replace', receiver['ipv6'],
                'lladdr', receiver['mac'], 'nud', 'permanent', 'dev', 'eth0')
        # Every denial needs a positive control: otherwise an unroutable fixture
        # could make a broken firewall appear secure.
        for name, sender, receiver, address, _, options in cases:
            if not probe(sender, receiver, address, **options):
                raise AssertionError('unfiltered positive control failed: ' + name)
        print(f'PASS: {len(cases)} unfiltered positive controls', flush=True)
        policy = json.loads(policy_bytes())
        old_policy(policy)
        for name, sender, receiver, address, expected, options in cases:
            if probe(sender, receiver, address, **options) != expected:
                raise AssertionError('old policy mismatch: ' + name)
        print(f'PASS: {len(cases)} existing-policy cases', flush=True)
        # These tables exist only in the fresh namespace created by this runner.
        run('iptables', '-F')
        run('ip6tables', '-F')
        for filename, bridge_filter in (('rejected-output.nft', 1), ('policy.nft', 0)):
            run('sysctl', '-qw', f'net.bridge.bridge-nf-call-iptables={bridge_filter}',
                f'net.bridge.bridge-nf-call-ip6tables={bridge_filter}')
            source = candidate(policy, filename)
            run('nft', '--check', '-f', '-', input=source)
            run('nft', '-f', '-', input=source)
            if filename == 'policy.nft':
                before = owned_tables()
                try:
                    run('nft', '-f', '-', input=source.replace('priority -10', 'priority invalid'))
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('invalid nftables transaction succeeded')
                if owned_tables() != before:
                    raise AssertionError('failed replacement changed installed rules')
                run('nft', '-f', '-', input=source)
                if owned_tables() != before:
                    raise AssertionError('repeat installation changed rule structure')
                print('PASS: atomic failure preserves policy; repeat installation does not duplicate rules', flush=True)
            failures = []
            for name, sender, receiver, address, expected, options in cases:
                actual = probe(sender, receiver, address, **options)
                if actual != expected:
                    failures.append(name)
            if filename == 'rejected-output.nft':
                expected_failures = ['egress other link', 'forged routed same egress',
                                     'forged routed other egress']
                if failures != expected_failures:
                    raise AssertionError(f'negative control changed: {failures}')
                print('PASS: rejected bridge-output design reproduces its three routing leaks', flush=True)
            elif failures:
                print(run('nft', '-j', 'list', 'ruleset'), flush=True)
                raise AssertionError('nft policy mismatches: ' + ', '.join(failures))
            else:
                print(f'PASS: {len(cases)} native nftables cases with bridge traversal disabled', flush=True)
            run('nft', 'delete', 'table', 'inet', 'codex_sandbox')
            run('nft', 'delete', 'table', 'bridge', 'codex_sandbox')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('run as root inside a Linux guest')
    handle_cancellation()
    if len(sys.argv) == 3 and sys.argv[1] == '--inside':
        inside(sys.argv[2])
    elif len(sys.argv) == 1:
        process = subprocess.Popen(['unshare', '--net', sys.executable, __file__,
                                    '--inside', os.readlink('/proc/self/ns/net')], start_new_session=True)
        try:
            raise SystemExit(process.wait())
        finally:
            ignore_cancellation()
            # Reuse the launcher's tested whole-group drain, including children
            # left behind after the wrapper exits. This group is ours alone.
            stop_build(process)
    else:
        raise SystemExit('no arguments expected')
