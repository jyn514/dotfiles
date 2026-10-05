#!/usr/bin/env python3
"""Explicit owner of the experimental rootless Docker VM and policy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.host import Host, SOURCE, GUEST, atomic_json, command, machines, private_directory, shares
from network_policy import policy_bytes
from lima.docker_client import docker_client, pin_buildx, pin_docker
from lima.docker_platform import current


class DockerHost(Host):
    provider = 'lima-docker'
    containerd_user = False

    def virtiofs_map(self, record):
        if (record.get('vm_type') != 'qemu' and
                record.get('vm_identity_source') != 'guest-machine-id' and
                not (sys.platform == 'linux' and record.get('mount_type') == 'virtiofs')):
            return None
        mapping = record.get('virtiofs_map')
        if not mapping:
            raise ValueError('Linux Docker VM predates UID mapping; create a new instance and state directory')
        return mapping

    def bind_check_argv(self, record):
        arguments = super().bind_check_argv(record)
        mapping = self.virtiofs_map(record)
        if mapping is None:
            return arguments
        return ('sudo', 'setpriv', f"--reuid={mapping['guest_uid']}",
                f"--regid={mapping['guest_gid']}", '--clear-groups', *arguments)

    def prepare_virtiofs(self, record):
        mapping = self.virtiofs_map(record)
        if mapping is None:
            return None
        qemu = shutil.which('qemu-system-x86_64')
        daemon = next((path for path in ('/usr/libexec/virtiofsd', '/usr/lib/virtiofsd')
                       if os.access(path, os.X_OK)), None)
        if qemu is None:
            raise ValueError('Linux virtiofs requires qemu-system-x86_64 in PATH')
        if daemon is None:
            raise ValueError('Linux virtiofs requires an executable virtiofsd at '
                             '/usr/libexec/virtiofsd or /usr/lib/virtiofsd')
        root = private_directory(self.state / 'virtiofs')
        binary = private_directory(root / 'bin') / 'qemu-system-x86_64'
        if not binary.exists():
            binary.symlink_to(Path(qemu).resolve(strict=True))
        wrapper = root / 'uidmapped-virtiofsd'
        source = SOURCE / 'docker/uidmapped-virtiofsd.sh'
        if not wrapper.exists():
            shutil.copyfile(source, wrapper)
            wrapper.chmod(0o700)
        if hashlib.sha256(wrapper.read_bytes()).hexdigest() != mapping['wrapper_digest']:
            raise ValueError('UID-mapped virtiofs daemon changed; repair the host state')
        directory = private_directory(root / 'share/qemu/vhost-user')
        registration = directory / '50-codex-sandbox-virtiofs.json'
        expected = {'type': 'fs', 'binary': str(wrapper)}
        if registration.exists():
            if json.loads(registration.read_text()) != expected:
                raise ValueError('UID-mapped virtiofs registration changed')
        else:
            atomic_json(registration, expected)
        return {**os.environ, 'QEMU_SYSTEM_X86_64': str(binary),
                'CODEX_SANDBOX_VIRTIOFSD': daemon,
                'CODEX_SANDBOX_UID_MAP': f":{mapping['guest_uid']}:{mapping['host_uid']}:1:",
                'CODEX_SANDBOX_GID_MAP': f":{mapping['guest_gid']}:{mapping['host_gid']}:1:"}

    def verify_virtiofs(self, record):
        mapping = self.virtiofs_map(record)
        if mapping is None:
            return
        scratch = self.state / 'scratch'
        ownership = self.guest(record, 'sudo', 'stat', '-c', '%u:%g', str(scratch),
                               capture_output=True, text=True).stdout.strip()
        expected = f"{mapping['guest_uid']}:{mapping['guest_gid']}"
        if ownership != expected:
            raise ValueError(f'Linux virtiofs UID map is inactive ({ownership}; expected {expected}); restart through docker_host.py')
        pids = self.guest(record, 'pgrep', '-x', 'dockerd',
                          capture_output=True, text=True).stdout.split()
        if len(pids) != 1 or not pids[0].isdigit():
            raise ValueError('expected exactly one rootless Docker daemon')
        for kind in ('uid', 'gid'):
            lines = self.guest(record, 'cat', f'/proc/{pids[0]}/{kind}_map',
                               capture_output=True, text=True).stdout.splitlines()
            pairs = [tuple(map(int, line.split())) for line in lines]
            container_id = mapping['host_' + kind]
            guest_id = mapping['guest_' + kind]
            if not any(start <= container_id < start + length and
                       outer + container_id - start == guest_id
                       for start, outer, length in pairs):
                raise ValueError(f'Docker {kind} namespace does not map agent ID to virtiofs owner')

    def machine(self, record):
        """Runtime lookup checks identity; setup/doctor owns configuration drift."""
        return self.machine_identity(record)

    def guest_argv(self, record, *args):
        if 'socket' not in record:
            return super().guest_argv(record, *args)
        # The socket's VM directory was checked by the caller's runtime audit.
        # Keep Lima's login shell and quoting without another limactl process.
        config = Path(record['socket']).parent.parent / 'ssh.config'
        remote = shlex.join(['sh', '-c', (SOURCE / 'guest-command.sh').read_text(),
                             'sh', shlex.join([str(arg) for arg in args])])
        return ['ssh', '-F', str(config), '-T', '-o', 'SendEnv=COLORTERM',
                '-o', 'LogLevel=ERROR', 'lima-' + record['instance'], remote]

    def source_files(self):
        return {'boot-credential.py': SOURCE / 'boot-credential.py',
                'mount-shares.py': SOURCE / 'mount-shares.py',
                'mounts.py': SOURCE / 'mounts.py',
                'install-slirp4netns.py': SOURCE / 'install-slirp4netns.py',
                'rootless-network.json': SOURCE / 'rootless-network.json',
                'docker-policy.py': SOURCE / 'docker/policy.py',
                'docker-install.py': SOURCE / 'docker/install.py',
                'docker-user.py': SOURCE / 'docker/configure-user.py',
                'nftables.py': SOURCE / 'docker/nftables.py',
                'network.nft': SOURCE / 'docker/network.nft',
                'docker-daemon.json': SOURCE / 'docker/daemon.json',
                'docker-service.conf': SOURCE / 'docker/docker-service.conf',
                'docker-reclaim.py': SOURCE / 'docker/reclaim.py',
                **{name: SOURCE / 'docker' / name for name in
                   ('sandbox.slice', 'sandbox-reclaim.service', 'sandbox-reclaim.timer')}}

    def install_snapshot(self, record, temporary):
        self.guest(record, 'sudo', 'mkdir', '-p', GUEST)
        for name in record['files']:
            self.guest(record, 'sudo', 'install', '-m', '0644', temporary + '/' + name, GUEST + '/' + name)
        self.guest(record, 'sudo', 'python3', GUEST + '/mount-shares.py', input=json.dumps(record).encode())
        self.guest(record, 'python3', GUEST + '/docker-user.py')

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
            configuration = current()
            record = self.record()
            if record['instance'] != instance or record['shares'] != requested:
                raise ValueError('Docker setup identity changed; use a separate state directory')
            if record['phase'] == 'ready':
                record = self.start()
                self.doctor(record)
                return record
            if record.get('firewall') != 'nftables':
                raise ValueError('old Docker setup is incomplete; provision a new instance and state directory')
        else:
            if instance in machines():
                raise ValueError('refusing to adopt an existing Docker VM')
            configuration = current()
            client_path = client or configuration.default_client or shutil.which('docker')
            if client_path is None:
                raise ValueError('Docker CLI is required; pass --client PATH or install Docker CLI')
            client = Path(client_path).resolve(strict=True)
            if not command(str(client), '--version', capture_output=True, text=True).stdout.startswith('Docker version '):
                raise ValueError('the prototype requires the real Docker CLI, not the Podman alias')
            config = private_directory(self.state / 'client')
            atomic_json(config / 'config.json', {})
            pin_buildx(self.state)
            client_artifact = pin_docker(self.state, client)
            snapshot = private_directory(self.state / 'source')
            for name, source in self.source_files().items():
                shutil.copyfile(source, snapshot / name)
            (snapshot / 'network-policy.json').write_bytes(policy_bytes())
            generation = uuid.uuid4().hex
            template = {
                'minimumLimaVersion': '1.2.1', 'vmType': configuration.vm_type,
                'arch': configuration.guest_arch, 'cpus': 8, 'memory': '8GiB',
                'disk': '100GiB', 'mountType': configuration.mount_type, 'mounts': requested,
                'images': [{'location': configuration.image, 'arch': configuration.guest_arch,
                            'digest': configuration.image_digest}],
                'containerd': {'system': False, 'user': False},
                'ssh': {'loadDotSSHPubKeys': False, 'forwardAgent': False},
                'hostResolver': {'enabled': True, 'ipv6': False,
                                 'hosts': {'host.docker.internal': 'host.lima.internal'}},
                'propagateProxyEnv': False, 'env': {
                    'SANDBOX_GENERATION': generation,
                    'SANDBOX_DOCKER_ARCH': configuration.guest_arch,
                },
                'provision': [{'mode': 'dependency', 'file': str(snapshot / 'install-slirp4netns.py')},
                              {'mode': 'system', 'file': str(snapshot / 'docker-install.py')}],
                'portForwards': [{'guestSocket': '/run/user/{{.UID}}/docker.sock',
                                  'hostSocket': '{{.Dir}}/sock/docker.sock'}],
            }
            atomic_json(self.state / 'host.yaml', template)
            command('limactl', 'validate', str(self.state / 'host.yaml'))
            record = {'schema': 1, 'provider': self.provider, 'phase': 'creating',
                      'instance': instance, 'namespace': 'default', 'generation': generation, 'firewall': 'nftables',
                      'vm_type': configuration.vm_type,
                      'mount_type': configuration.mount_type,
                      'shares': requested, 'client': str(client), 'client_artifact': client_artifact,
                      'template_digest': hashlib.sha256((self.state / 'host.yaml').read_bytes()).hexdigest(),
                      'network_digest': hashlib.sha256(policy_bytes()).hexdigest(),
                      'files': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in snapshot.iterdir()}}
            if configuration.vm_type == 'qemu':
                if not 0 < os.getuid() < 65536 or not 0 < os.getgid() < 65536:
                    raise ValueError('Linux virtiofs mapping requires host UID and GID in 1..65535')
                # Rootless Docker maps container ID 1 to guest subordinate ID 100000.
                # Map the host agent ID to the guest ID seen by container agent ID.
                record['virtiofs_map'] = {
                    'host_uid': os.getuid(), 'host_gid': os.getgid(),
                    'guest_uid': 99999 + os.getuid(), 'guest_gid': 99999 + os.getgid(),
                    'wrapper_digest': hashlib.sha256(
                        (SOURCE / 'docker/uidmapped-virtiofsd.sh').read_bytes()).hexdigest()}
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
        command('limactl', 'start', '--tty=false', instance, env=self.prepare_virtiofs(record))
        machine = self.machine(record)
        if configuration.vm_type == 'vz':
            record['vm_identity'] = hashlib.sha256(
                (Path(machine['dir']) / 'vz-identifier').read_bytes()
            ).hexdigest()
        record['socket'] = str(Path(machine['dir']) / 'sock/docker.sock')
        atomic_json(self.record_path, record)
        self.configure_ssh(record)
        if configuration.vm_type == 'qemu':
            machine_id = self.guest(record, 'cat', '/etc/machine-id', capture_output=True,
                                    text=True).stdout.strip()
            if not re.fullmatch(r'[0-9a-f]{32}', machine_id):
                raise ValueError('guest machine identity is missing or malformed')
            record['vm_identity'] = hashlib.sha256(machine_id.encode()).hexdigest()
            record['vm_identity_source'] = 'guest-machine-id'
            atomic_json(self.record_path, record)
        with self.staged_snapshot(record) as staging:
            self.install_snapshot(record, staging)
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
        self.doctor(record)
        if 'docker-reclaim.py' in record['files']:
            # Only first provisioning reaches here. Ready-state setup returns
            # above, preserving an operator's disabled timer during repair.
            self.guest(record, 'systemctl', '--user', 'enable', '--now',
                       'sandbox-reclaim.timer', timeout=30)
        record['phase'] = 'ready'
        atomic_json(self.record_path, record)
        return record

    def verify_runtime(self, record):
        # This controlled VM installs its firewall in ExecStartPost. Admission
        # needs service readiness; configuration drift belongs to setup/doctor.
        self.runtime_epoch(record)
        self.verify_virtiofs(record)

    def doctor(self, record):
        epoch = self.runtime_epoch(record)
        self.verify_virtiofs(record)
        self.verify(record)
        if self.runtime_epoch(record) != epoch:
            raise ValueError('Docker restarted during doctor; retry the audit')

    def source_drift(self, record):
        current = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for name, path in self.source_files().items()}
        current['network-policy.json'] = hashlib.sha256(policy_bytes()).hexdigest()
        installed = record['files']
        return {
            'added': sorted(current.keys() - installed.keys()),
            'changed': sorted(name for name in current.keys() & installed.keys()
                              if current[name] != installed[name]),
            'removed': sorted(installed.keys() - current.keys()),
        }

    def start(self):
        record = self.record()
        if record['phase'] != 'ready':
            raise ValueError('setup is incomplete; rerun setup with the same shares')
        self.machine(record)
        command('limactl', 'start', '--tty=false', record['instance'], env=self.prepare_virtiofs(record))
        self.verify_runtime(record)
        return record

    def runtime_epoch(self, record):
        machine = self.machine(record)
        # This fixed systemctl query needs no login-shell setup. Reuse Lima's
        # generated connection settings without starting limactl for every check.
        result = command('ssh', '-F', machine['sshConfigFile'], '-T', machine['hostname'],
                         'systemctl', '--user', 'show', 'docker.service',
                         '--property=ActiveState', '--property=SubState', '--property=InvocationID',
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10).stdout
        values = dict(line.split('=', 1) for line in result.splitlines())
        if (values.get('ActiveState') != 'active' or values.get('SubState') != 'running' or
                not re.fullmatch(r'[0-9a-f]{32}', values.get('InvocationID', ''))):
            raise ValueError('Docker policy readiness has not completed')
        return values['InvocationID']

    def verify(self, record, *, quiet=False):
        super().machine(record)
        installed = self.guest(record, 'sha256sum', GUEST + '/docker-policy.py', capture_output=True, text=True).stdout.split()[0]
        if installed != record['files']['docker-policy.py']:
            raise ValueError('installed Docker verifier changed')
        self.guest(record, 'python3', GUEST + '/docker-policy.py', 'check', input=json.dumps(record), text=True)

    def reclaim_status(self, record):
        if 'docker-reclaim.py' not in record['files']:
            return {'state': 'not-installed'}
        output = self.guest(record, 'systemctl', '--user', 'show',
                            'sandbox-reclaim.timer', 'sandbox-reclaim.service',
                            '--property=Id,LoadState,ActiveState,SubState,UnitFileState,Result,'
                            'ExecMainStatus,NextElapseUSecMonotonic,LastTriggerUSec',
                            capture_output=True, text=True).stdout
        units = {}
        for block in output.strip().split('\n\n'):
            values = dict(line.split('=', 1) for line in block.splitlines())
            units[values.pop('Id')] = values
        return units

    def reclaim(self, operation):
        record = self.record()
        self.machine(record)
        if 'docker-reclaim.py' not in record['files']:
            raise ValueError('reclamation is not installed; use a new VM/state generation')
        if operation not in ('once', 'enable', 'disable'):
            raise ValueError('expected once, enable, or disable')
        if operation == 'disable':
            # Recovery remains available when Docker is stopped or unready.
            self.guest(record, 'systemctl', '--user', 'disable', '--now', 'sandbox-reclaim.timer')
            self.guest(record, 'systemctl', '--user', 'stop', 'sandbox-reclaim.service', timeout=30)
            installed = self.guest(record, 'sha256sum', GUEST + '/docker-reclaim.py',
                                   capture_output=True, text=True).stdout.split()[0]
            if installed != record['files']['docker-reclaim.py']:
                raise ValueError('installed reclaim helper changed; cannot confirm idle')
            self.guest(record, 'python3', GUEST + '/docker-reclaim.py', '--check-idle', timeout=10)
        else:
            self.doctor(record)
            arguments = (['enable', '--now', 'sandbox-reclaim.timer'] if operation == 'enable'
                         else ['start', 'sandbox-reclaim.service'])
            self.guest(record, 'systemctl', '--user', *arguments, timeout=30)
        return {**record, 'reclamation': self.reclaim_status(record)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/codex-sandbox-docker')
    sub = parser.add_subparsers(dest='operation', required=True)
    setup = sub.add_parser('setup')
    setup.add_argument('--instance', default='sandbox-host-docker')
    setup.add_argument('--share-read', action='append')
    setup.add_argument('--share-write', action='append')
    setup.add_argument('--client', type=Path)
    setup.add_argument('--default-context', help='create or update this Docker context and select it as the default')
    for name in ('start', 'stop', 'status', 'doctor', 'upgrade', 'pin-buildx'):
        sub.add_parser(name)
    pin = sub.add_parser('pin-client')
    pin.add_argument('--source', type=Path)
    reclaim = sub.add_parser('reclaim', help='run, enable, or disable guest cache reclamation')
    reclaim.add_argument('action', choices=('once', 'enable', 'disable'), nargs='?', default='once')
    args = parser.parse_args()
    host = DockerHost(args.state)
    with host.locked():
        if args.operation == 'setup':
            record = host.setup(args.instance, args.share_read, args.share_write, args.client)
            if args.default_context:
                client = docker_client(host.state, record)
                contexts = command(client, 'context', 'ls', '--format', '{{.Name}}',
                                   capture_output=True, text=True).stdout.splitlines()
                operation = 'update' if args.default_context in contexts else 'create'
                command(client, 'context', operation, args.default_context,
                        '--description', 'Docker in Lima ' + record['instance'],
                        '--docker', 'host=unix://' + record['socket'])
                command(client, 'context', 'use', args.default_context)
        elif args.operation == 'status':
            record = host.record()
            host.verify_runtime(record)
            record = {**record, 'reclamation': host.reclaim_status(record)}
        elif args.operation == 'doctor':
            record = host.record()
            host.doctor(record)
            drift = host.source_drift(record)
            record = {**record, 'reclamation': host.reclaim_status(record), 'source_drift': drift}
            if any(drift.values()):
                changes = '; '.join(f"{kind}: {', '.join(names)}" for kind, names in drift.items() if names)
                upgrade = shlex.join([sys.executable, str(Path(__file__).resolve()),
                                      '--state', str(host.state), 'upgrade'])
                print(f'Installed Docker configuration passed; current source differs ({changes}). '
                      f'Use {upgrade} to apply it; upgrade restarts shared Docker '
                      'and stops running containers.', file=sys.stderr)
        elif args.operation == 'upgrade':
            record = host.upgrade()
        elif args.operation == 'reclaim':
            record = host.reclaim(args.action)
        elif args.operation == 'pin-buildx':
            host.record()
            print(pin_buildx(host.state))
            return
        elif args.operation == 'pin-client':
            record = host.record()
            source = args.source or record.get('client')
            if source is None:
                raise ValueError('Docker CLI is required; pass --source PATH')
            record['client_artifact'] = pin_docker(host.state, source)
            atomic_json(host.record_path, record)
        else:
            record = getattr(host, args.operation)()
        print(json.dumps(record))


if __name__ == '__main__':
    main()
