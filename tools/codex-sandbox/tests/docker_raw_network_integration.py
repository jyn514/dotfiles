"""Exercise Ethernet routing attacks between owned containers in a disposable VM."""

import argparse
import json
import ipaddress
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
sys.path.insert(0, str(ROOT / 'experiments/nftables'))
from probe import ready, stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--disposable-instance', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    assert runtime.record['instance'] == args.disposable_instance != 'sandbox-host-docker'
    assert not runtime.run(['ps', '-q'], capture_output=True).stdout.strip(), 'VM has running workloads'
    image = runtime.inspect_image(args.image)
    prefix = 'raw-policy-' + uuid.uuid4().hex[:12]
    networks, containers = [], []
    uid = runtime.host.machine(runtime.record)['config']['user']['uid']
    namespace = ['dockerd-rootless-setuptool.sh', 'nsenter', '--', 'nsenter',
                 f'--net=/run/user/{uid}/dockerd-rootless/netns', '--']

    def network(suffix, internal):
        name = prefix + '-' + suffix
        networks.append(name)
        runtime.create_relay_network(name, internal=internal, owner=uuid.uuid4().hex)
        return name

    def container(suffix, network):
        name = prefix + '-' + suffix
        containers.append(name)
        runtime.run(['run', '-d', '--name', name, '--network', network,
                     '--cap-drop=ALL', '--cap-add=NET_RAW', '--memory=64m', '--pids-limit=16',
                     '--mount', f'type=bind,src={ROOT / "experiments/nftables/packet.py"},dst=/packet.py,readonly',
                     '--entrypoint', 'sleep', image.config, '300'], stdout=subprocess.DEVNULL)
        address = json.loads(runtime.run(['inspect', name], capture_output=True).stdout)[0]['NetworkSettings']['Networks'][network]
        bridge = json.loads(runtime.run(['network', 'inspect', network], capture_output=True).stdout)[0]['Options']['com.docker.network.bridge.name']
        mac = json.loads(runtime.guest([*namespace, 'ip', '-j', 'link', 'show', bridge], capture_output=True,
                                      text=True).stdout)[0]['address']
        return {'name': name, 'ip': address['IPAddress'], 'mac': address['MacAddress'], 'gateway_mac': mac}

    def probe(sender, receiver, *, routed, expected, forged=False):
        listener = subprocess.Popen(runtime.argv(['exec', receiver['name'], 'python3', '/packet.py',
                                                   'listen', '--timeout', '2']), stdout=subprocess.PIPE, text=True)
        try:
            ready(listener)
            runtime.run(['exec', sender['name'], 'python3', '/packet.py', 'send',
                         '--address', receiver['ip'], '--mac', sender['gateway_mac'] if routed else receiver['mac'],
                         '--source', str(ipaddress.IPv4Address(sender['ip']) + 99) if forged else sender['ip']],
                        capture_output=True)
            status = listener.wait(timeout=5)
            assert status == (0 if expected else 1), (sender, receiver, routed, forged, expected, status)
        finally:
            stop(listener)

    try:
        link, other_link = network('link', True), network('other-link', True)
        egress, other_egress = network('egress', False), network('other-egress', False)
        public = container('public', 'codex-public-only')
        public_peer = container('public-peer', 'codex-public-only')
        local = container('link-a', link)
        local_peer = container('link-b', link)
        remote = container('link-c', other_link)
        outbound = container('egress-a', egress)
        outbound_peer = container('egress-b', egress)
        outbound_remote = container('egress-c', other_egress)
        # Real peer delivery proves that NET_RAW and the receiver work, including
        # with forged on-link source addresses, before relying on a routing denial.
        # Internal containers have no default route; an off-link spoof may be
        # dropped by their own reverse-path check rather than our firewall.
        for sender, receiver in ((public, public_peer), (local, local_peer), (outbound, outbound_peer)):
            for forged in (False, True):
                probe(sender, receiver, routed=False, expected=True, forged=forged)
        for sender, receiver in ((local, local_peer), (local, remote), (outbound, outbound_peer),
                                 (outbound, outbound_remote), (outbound, local), (outbound, public),
                                 (public, local)):
            for forged in (False, True):
                probe(sender, receiver, routed=True, expected=False, forged=forged)
        print('PASS: six raw-packet peer controls and fourteen routed/forged isolation cases', flush=True)
    finally:
        for name in reversed(containers):
            runtime.terminate(name)
        for name in reversed(networks):
            runtime.run(['network', 'rm', name], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
