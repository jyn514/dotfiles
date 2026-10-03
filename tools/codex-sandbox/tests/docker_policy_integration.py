"""Exercise policy and restart failure in a caller-owned disposable Docker VM.

This stops Docker in that VM. Never point it at a VM used by real sessions.
"""

import argparse
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from lima.host import GUEST, verification_scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--image', required=True, help='local image containing python3')
    parser.add_argument('--disposable-instance', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    assert runtime.record['instance'] == args.disposable_instance
    assert args.disposable_instance != 'sandbox-host-docker'
    assert runtime.run(['ps', '-q'], capture_output=True).stdout.strip() == '', 'VM has running workloads'
    image = runtime.inspect_image(args.image)
    prefix = 'docker-policy-test-' + uuid.uuid4().hex[:12]
    link, other, egress = [prefix + '-' + suffix for suffix in ('link', 'other', 'egress')]
    service = prefix + '-service'
    networks = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'host.lima.internal:{server.server_port}'

    def probe(network, mode, target):
        with runtime.workload(image, prefix + '-' + uuid.uuid4().hex[:8], [
                '--network', network, '--dns', '10.0.2.3', '--user', '0',
                '--mount', f'type=bind,src={ROOT / "tests/docker_network_probe.py"},dst=/probe.py,readonly',
                '--entrypoint', 'python3'], ['/probe.py', mode, target]) as process:
            assert process.wait(timeout=30) == 0

    def published_endpoint(container):
        # Docker allocates the guest loopback port at start, asynchronously to
        # workload's attached transport. Do not reserve a fixed test port.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = runtime.run(['port', container, '18765/tcp'], capture_output=True,
                                 check=False, timeout=5)
            target = result.stdout.strip()
            if result.returncode == 0 and target:
                address, port = target.rsplit(':', 1)
                assert address == '127.0.0.1' and 0 < int(port) < 65536, target
                return target
            time.sleep(0.1)
        raise AssertionError(f'no published loopback port for {container}')

    try:
        for name, internal in ((link, True), (other, True), (egress, False)):
            runtime.create_relay_network(name, internal=internal, owner=uuid.uuid4().hex)
            networks.append(name)
        # Relay egress bridges are cse*, not the csp* used by Strix. Use the
        # service-network API to own a bridge subject to the public-only policy.
        runtime.create_public_service_network(service, uuid.uuid4().hex)
        networks.append(service)
        probe(egress, 'allow', endpoint)
        for network in ('codex-public-only', service):
            probe(network, 'deny', endpoint)
        probe('codex-public-only', 'public', '-')
        probe('codex-public-only', 'dns-tcp', '10.0.2.3')
        with ExitStack() as stack:
            # Docker's host network is not its detached bridge namespace.
            # Own a transient guest unit there as the positive control for
            # INPUT filtering, and stop it before restarting Docker below.
            uid = runtime.host.machine(runtime.record)['config']['user']['uid']
            unit = prefix + '-gateway.service'
            stack.callback(runtime.guest, ['systemctl', '--user', 'stop', unit], timeout=30)
            runtime.guest(['systemd-run', '--user', '--unit', unit, '--collect',
                'dockerd-rootless-setuptool.sh', 'nsenter', '--',
                'nsenter', f'--net=/run/user/{uid}/dockerd-rootless/netns', '--',
                'python3', '-m', 'http.server', '18766', '--bind', '10.254.254.1'], timeout=30)
            probe(egress, 'allow', '10.254.254.1:18766')
            for network in ('codex-public-only', service):
                probe(network, 'deny', '10.254.254.1:18766')
            peer = prefix + '-peer'
            stack.enter_context(runtime.workload(image, peer,
                ['--network', link, '--entrypoint', 'python3'], ['-m', 'http.server', '18765']))
            address = runtime.network_address(peer, link)
            probe(link, 'allow', address + ':18765')
            probe(other, 'deny', address + ':18765')
            probe('codex-public-only', 'deny', address + ':18765')
            for index, network in enumerate(('codex-public-only', service)):
                public_peer = prefix + '-public-peer-' + str(index)
                stack.enter_context(runtime.workload(image, public_peer,
                    ['--network', network, '--publish', '127.0.0.1::18765',
                     '--entrypoint', 'python3'], ['-m', 'http.server', '18765']))
                probe(network, 'allow', runtime.network_address(public_peer, network) + ':18765')
                target = published_endpoint(public_peer)
                # A rootless port proxy could accept TCP while INPUT rejected
                # the container's reply. Demand an entire HTTP 200 in the VM,
                # then through Lima's host loopback forwarding as well.
                runtime.guest(['python3', str(ROOT / 'tests/docker_network_probe.py'),
                               'http', target], timeout=30)
                subprocess.run([sys.executable, str(ROOT / 'tests/docker_network_probe.py'),
                                'http', target], check=True, timeout=30)
        print('PASS: public DNS/HTTP, private-host denial, internal-link isolation, IPv6 denial', flush=True)
        print('PASS: complete VM/host loopback HTTP 200 on cs-public and owned csp* bridge', flush=True)
        if runtime.record.get('firewall') == 'nftables':
            namespace = ['dockerd-rootless-setuptool.sh', 'nsenter', '--', 'nsenter',
                         f'--net=/run/user/{uid}/dockerd-rootless/netns', '--']
            try:
                runtime.guest([*namespace, 'nft', 'flush', 'chain', 'inet', 'codex_sandbox', 'forward'])
                try:
                    runtime.host.verify(runtime.record)
                except subprocess.CalledProcessError:
                    pass
                else:
                    raise AssertionError('modified native rules were accepted')
            finally:
                runtime.guest(['python3', GUEST + '/docker-policy.py', 'install'])
                runtime.host.verify(runtime.record)
            print('PASS: native verifier rejects changed rule expressions and accepts restored policy', flush=True)
            unready = prefix + '-unready'
            owner = uuid.uuid4().hex
            networks.append(unready)
            try:
                runtime.guest([*namespace, 'sysctl', '-qw', 'net.bridge.bridge-nf-call-iptables=1'])
                try:
                    runtime.create_relay_network(unready, internal=True, owner=owner)
                except subprocess.CalledProcessError:
                    pass
                else:
                    raise AssertionError('network became ready after bridge traversal changed')
                assert runtime.relay_owner(unready) == owner, 'failed readiness lost cleanup ownership'
            finally:
                runtime.guest(['python3', GUEST + '/docker-policy.py', 'install'])
                runtime.host.verify(runtime.record)
            print('PASS: post-create check rejects changed sysctls and retains network ownership', flush=True)
        old_epoch = runtime.host.runtime_epoch(runtime.record)
        sleeper = prefix + '-restart'
        runtime.run(['run', '-d', '--name', sleeper, '--network', 'none', '--entrypoint', 'sleep', image.config, '300'],
                    stdout=subprocess.DEVNULL)
        try:
            runtime.guest(['systemctl', '--user', 'restart', 'docker'], timeout=240)
            with verification_scope():
                runtime.verify()
            assert runtime.host.runtime_epoch(runtime.record) != old_epoch
            assert runtime.run(['inspect', '--format', '{{.State.Running}}', sleeper], capture_output=True).stdout.strip() == 'false'
        finally:
            runtime.terminate(sleeper)
        # The owned install source is restored even if the failed activation
        # leaves Docker stopped. Ordinary launch must never repair it itself.
        installed = GUEST + '/network-policy.json'
        original = runtime.guest(['cat', installed], capture_output=True).stdout
        try:
            runtime.guest(['sudo', 'tee', installed], input=b'{}', stdout=subprocess.DEVNULL)
            try:
                runtime.guest(['systemctl', '--user', 'restart', 'docker'], timeout=240)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('Docker started despite failed policy installation')
            with verification_scope():
                try:
                    runtime.verify()
                except ValueError:
                    pass
                else:
                    raise AssertionError('failed post-start policy was accepted')
        finally:
            runtime.guest(['sudo', 'tee', installed], input=original, stdout=subprocess.DEVNULL)
            runtime.guest(['systemctl', '--user', 'restart', 'docker'], timeout=240)
            with verification_scope():
                runtime.verify()
        print('PASS: restart reinstalls policy, stops old workloads, and rejects failed policy activation', flush=True)
    finally:
        for network in reversed(networks):
            runtime.run(['network', 'rm', network], stdout=subprocess.DEVNULL)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
