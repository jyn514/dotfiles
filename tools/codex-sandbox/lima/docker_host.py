#!/usr/bin/env python3
"""Explicit owner of the experimental rootless Docker VM and policy."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.host import Host, SOURCE, GUEST, atomic_json, command, machines, private_directory, shares
from network_policy import policy_bytes
from lima.docker_client import pin_buildx


class DockerHost(Host):
    provider = 'lima-docker'
    containerd_user = False

    def setup(self, instance='sandbox-host-docker', read=None, write=None, client=None):
        if not re.fullmatch(r'sandbox-host-docker(?:-[a-z0-9-]+)?', instance):
            raise ValueError('Docker prototype requires its own sandbox-host-docker instance')
        scratch = private_directory(self.state / 'scratch')
        home_share = Path.home().resolve(strict=True) if read is None and write is None else None
        requested = shares([], [home_share]) if home_share is not None else shares(read or [], write or [])
        if not any(scratch.is_relative_to(Path(item['location'])) and item['writable'] for item in requested):
            requested = shares([item['location'] for item in requested if not item['writable']],
                               [*[item['location'] for item in requested if item['writable']], scratch])
        # Default home sharing is deliberate; explicit test shares must not
        # expose their control record or immutable provisioning snapshot.
        if any(not (home_share is not None and Path(item['location']) == home_share) and
               (self.state.is_relative_to(Path(item['location'])) or
                (Path(item['location']).is_relative_to(self.state) and
                 not Path(item['location']).is_relative_to(scratch))) for item in requested):
            raise ValueError('a share exposes the host control directory')
        if self.record_path.exists():
            record = self.record()
            if record['instance'] != instance or record['shares'] != requested:
                raise ValueError('Docker setup identity changed; use a separate state directory')
            if record['phase'] == 'ready':
                return self.start()
            if record.get('firewall') != 'nftables':
                raise ValueError('old Docker setup is incomplete; provision a new instance and state directory')
        else:
            if instance in machines():
                raise ValueError('refusing to adopt an existing Docker VM')
            client = Path(client or '/opt/homebrew/bin/docker').resolve(strict=True)
            if not command(str(client), '--version', capture_output=True, text=True).stdout.startswith('Docker version '):
                raise ValueError('the prototype requires the real Docker CLI, not the Podman alias')
            config = private_directory(self.state / 'client')
            atomic_json(config / 'config.json', {})
            pin_buildx(self.state)
            snapshot = private_directory(self.state / 'source')
            inputs = {'boot-credential.py': SOURCE / 'boot-credential.py',
                      'mount-shares.py': SOURCE / 'mount-shares.py',
                      'install-slirp4netns.py': SOURCE / 'install-slirp4netns.py',
                      'rootless-network.json': SOURCE / 'rootless-network.json',
                      'docker-policy.py': SOURCE / 'docker/policy.py',
                      'docker-install.py': SOURCE / 'docker/install.py',
                      'docker-user.py': SOURCE / 'docker/configure-user.py',
                      'nftables.py': SOURCE / 'docker/nftables.py',
                      'network.nft': SOURCE / 'docker/network.nft',
                      'docker-daemon.json': SOURCE / 'docker/daemon.json'}
            for name, source in inputs.items():
                shutil.copyfile(source, snapshot / name)
            (snapshot / 'network-policy.json').write_bytes(policy_bytes())
            generation = uuid.uuid4().hex
            template = {
                'minimumLimaVersion': '1.2.1', 'vmType': 'vz', 'arch': 'aarch64',
                'cpus': 4, 'memory': '4GiB', 'disk': '64GiB', 'mountType': 'virtiofs', 'mounts': requested,
                'images': [{'location': 'http://cloud-images-archive.ubuntu.com/releases/noble/release-20250704/ubuntu-24.04-server-cloudimg-arm64.img',
                            'arch': 'aarch64', 'digest': 'sha256:bbecbb88100ee65497927ed0da247ba15af576a8855004182cf3c87265e25d35'}],
                'containerd': {'system': False, 'user': False},
                'ssh': {'loadDotSSHPubKeys': False, 'forwardAgent': False},
                'hostResolver': {'enabled': True, 'ipv6': False,
                                 'hosts': {'host.docker.internal': 'host.lima.internal'}},
                'propagateProxyEnv': False, 'env': {'SANDBOX_GENERATION': generation},
                'provision': [{'mode': 'dependency', 'file': str(snapshot / 'install-slirp4netns.py')},
                              {'mode': 'system', 'file': str(snapshot / 'docker-install.py')}],
                'portForwards': [{'guestSocket': '/run/user/{{.UID}}/docker.sock',
                                  'hostSocket': '{{.Dir}}/sock/docker.sock'}],
            }
            atomic_json(self.state / 'host.yaml', template)
            command('limactl', 'validate', str(self.state / 'host.yaml'))
            record = {'schema': 1, 'provider': self.provider, 'phase': 'creating',
                      'instance': instance, 'namespace': 'default', 'generation': generation, 'firewall': 'nftables',
                      'shares': requested, 'client': str(client),
                      'template_digest': hashlib.sha256((self.state / 'host.yaml').read_bytes()).hexdigest(),
                      'network_digest': hashlib.sha256(policy_bytes()).hexdigest(),
                      'files': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in snapshot.iterdir()}}
            atomic_json(self.record_path, record)
        if hashlib.sha256((self.state / 'host.yaml').read_bytes()).hexdigest() != record['template_digest']:
            raise ValueError('Docker template changed during setup')
        for name, digest in record['files'].items():
            if hashlib.sha256((self.state / 'source' / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Docker setup snapshot changed')
        if instance not in machines():
            if record['phase'] != 'creating':
                raise ValueError('recorded Docker VM disappeared; retain state and use a new identity')
            command('limactl', 'create', '--tty=false', '--name=' + instance, str(self.state / 'host.yaml'))
        machine = self.machine(record)
        record['config_digest'] = hashlib.sha256(json.dumps(machine['config'], sort_keys=True).encode()).hexdigest()
        if record['phase'] == 'installing':
            command('limactl', 'stop', '--force', '--tty=false', instance)
        record['phase'] = 'installing'
        atomic_json(self.record_path, record)
        command('limactl', 'start', '--tty=false', instance)
        machine = self.machine(record)
        record['vm_identity'] = hashlib.sha256((Path(machine['dir']) / 'vz-identifier').read_bytes()).hexdigest()
        record['socket'] = str(Path(machine['dir']) / 'sock/docker.sock')
        atomic_json(self.record_path, record)
        staging = self.guest(record, 'mktemp', '-d', capture_output=True, text=True).stdout.strip()
        try:
            self.guest(record, 'sudo', 'mkdir', '-p', GUEST)
            for name in record['files']:
                self.guest(record, 'tee', staging + '/' + name,
                           input=(self.state / 'source' / name).read_bytes(), stdout=subprocess.DEVNULL)
                self.guest(record, 'sudo', 'install', '-m', '0644', staging + '/' + name, GUEST + '/' + name)
            self.guest(record, 'sudo', 'python3', GUEST + '/mount-shares.py', input=json.dumps(record).encode())
            self.guest(record, 'python3', GUEST + '/docker-user.py')
        finally:
            self.guest(record, 'rm', '-rf', staging)
        info = json.loads(self.guest(record, 'docker', 'info', '--format', '{{json .}}', capture_output=True, text=True).stdout)
        record['engine_id'] = info['ID']
        networks = self.guest(record, 'docker', 'network', 'ls', '--format', '{{.Name}}', capture_output=True, text=True).stdout.splitlines()
        if 'codex-public-only' not in networks:
            self.guest(record, 'docker', 'network', 'create', '--subnet', '10.254.254.0/24',
                       '--ip-range', '10.254.254.128/25', '--gateway', '10.254.254.1',
                       '--label', 'dev.codex.generation=' + record['generation'],
                       '--opt', 'com.docker.network.bridge.name=cs-public', 'codex-public-only')
        network = json.loads(self.guest(record, 'docker', 'network', 'inspect', 'codex-public-only',
                                       capture_output=True, text=True).stdout)[0]
        if network['Labels'].get('dev.codex.generation') != record['generation']:
            raise ValueError('Docker public network belongs to another creator')
        record['network_id'] = network['Id']
        self.verify(record)
        record['phase'] = 'ready'
        atomic_json(self.record_path, record)
        return record

    def runtime_epoch(self, record):
        self.machine(record)
        result = self.guest(record, 'systemctl', '--user', 'show', 'docker.service',
                            '--property=ActiveState', '--property=SubState', '--property=InvocationID',
                            capture_output=True, text=True, timeout=10).stdout
        values = dict(line.split('=', 1) for line in result.splitlines())
        if (values.get('ActiveState') != 'active' or values.get('SubState') != 'running' or
                not re.fullmatch(r'[0-9a-f]{32}', values.get('InvocationID', ''))):
            raise ValueError('Docker policy readiness has not completed')
        return values['InvocationID']

    def verify(self, record, *, quiet=False):
        self.machine(record)
        installed = self.guest(record, 'sha256sum', GUEST + '/docker-policy.py', capture_output=True, text=True).stdout.split()[0]
        if installed != record['files']['docker-policy.py']:
            raise ValueError('installed Docker verifier changed')
        self.guest(record, 'python3', GUEST + '/docker-policy.py', 'check', input=json.dumps(record), text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/codex-sandbox-docker')
    sub = parser.add_subparsers(dest='operation', required=True)
    setup = sub.add_parser('setup')
    setup.add_argument('--instance', default='sandbox-host-docker')
    setup.add_argument('--share-read', action='append')
    setup.add_argument('--share-write', action='append')
    setup.add_argument('--client', type=Path)
    for name in ('start', 'stop', 'status', 'pin-buildx'):
        sub.add_parser(name)
    args = parser.parse_args()
    host = DockerHost(args.state)
    with host.locked():
        if args.operation == 'setup':
            record = host.setup(args.instance, args.share_read, args.share_write, args.client)
        elif args.operation == 'status':
            record = host.record()
            host.verify_runtime(record)
        elif args.operation == 'pin-buildx':
            host.record()
            print(pin_buildx(host.state))
            return
        else:
            record = getattr(host, args.operation)()
        print(json.dumps(record))


if __name__ == '__main__':
    main()
