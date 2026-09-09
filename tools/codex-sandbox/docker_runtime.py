"""Rootless Docker operations through the owned Lima-forwarded engine socket."""

import hashlib
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid

from lima.docker_host import DockerHost
from sandbox_runtime import VMRuntime, Image, RuntimeError, chain_id, digest, single_json, PROXY_ENV


class Docker(VMRuntime):
    provider = 'lima-docker'
    host_address = 'host.lima.internal'
    nonrecursive_bind = 'bind-recursive=disabled'

    def __init__(self, state):
        self.host = DockerHost(state)
        self.record = self.host.record()
        if self.record['phase'] != 'ready':
            raise RuntimeError('Docker prototype setup is incomplete')
        machine = self.host.machine(self.record)
        if self.record['socket'] != str(Path(machine['dir']) / 'sock/docker.sock'):
            raise RuntimeError('Docker socket differs from recorded VM')
        self.verify()

    def argv(self, arguments, *, cwd=None):
        self.host.machine(self.record)
        if (arguments[0] in ('run', 'create', 'start', 'rm', 'kill', 'stop', 'exec', 'wait') or
                arguments[0] in ('network', 'volume') and arguments[1] in ('create', 'rm', 'connect', 'disconnect')):
            self.verify()
        ambient = (*PROXY_ENV, 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
                   'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'DOCKER_API_VERSION',
                   'BUILDX_BUILDER', 'BUILDKIT_HOST')
        return ['/usr/bin/env', *['-u' + name for name in ambient], self.record['client'],
                '--config', str(self.host.state / 'client'), '--host', 'unix://' + self.record['socket'],
                *arguments]

    def run(self, arguments, **kwargs):
        kwargs.setdefault('timeout', 30)
        return super().run(arguments, **kwargs)

    def inspect_image(self, reference):
        raw = single_json(self.run(['image', 'inspect', reference], capture_output=True).stdout)
        config = digest(raw['Id'])
        candidates = raw.get('RepoDigests') or []
        if '@' in reference:
            name, content = reference.rsplit('@', 1)
            repository = name.rsplit(':', 1)[0] if ':' in name.rsplit('/', 1)[-1] else name
            if repository + '@' + content not in candidates:
                raise RuntimeError('Docker image reference differs from its repository digest')
            immutable = reference
        elif candidates:
            immutable = sorted(candidates)[0]
            # BuildKit's local resolver needs the tag as well as the digest.
            # The digest still pins content if that tag later moves.
            repository, content = immutable.rsplit('@', 1)
            tags = [tag for tag in raw.get('RepoTags', []) if tag.rsplit(':', 1)[0] == repository]
            if tags:
                immutable = sorted(tags)[0] + '@' + content
        else:
            raise RuntimeError('Docker image has no repository digest; rebuild with sandbox-image')
        content = digest(immutable.rsplit('@', 1)[1])
        return Image(immutable, content, config, chain_id(raw['RootFS']['Layers']))

    def builder_image(self, reference):
        if '@sha256:' not in reference:
            raise RuntimeError('Docker builders must return sandbox-image repository digests')
        return self.inspect_image(reference).reference

    def build(self, tag, dockerfile, context, *, build_args=(), target=None):
        self.verify()
        arguments = ['buildx', 'build', '--builder', 'default', '--load', '--provenance=false',
                     '--file', str(dockerfile), '--tag', tag]
        for value in build_args:
            arguments += ['--build-arg', value]
        if target:
            arguments += ['--target', target]
        self.run([*arguments, str(context)], stdout=sys.stderr, timeout=1800)
        return self.resolve_image(tag)

    def workload_argv(self, image, arguments, command=(), *, cwd=None, operation='run'):
        self.verify()
        return self.argv([operation, '--pull=never', *arguments, image.config, *command], cwd=cwd)

    def agent_command(self, image, arguments):
        config = single_json(self.run(['image', 'inspect', image], capture_output=True).stdout)['Config']
        entrypoint = config.get('Entrypoint') or []
        command = list(arguments) if arguments else config.get('Cmd') or []
        if not isinstance(entrypoint, list) or not isinstance(command, list) or not entrypoint + command:
            raise RuntimeError('Docker image has no supported agent command')
        return [*entrypoint, *command]

    def forward_proxy(self, container):
        # Docker has no exec-kill API. Give each routed request a container
        # lifetime, so cancellation needs neither guest PIDs nor ctr internals.
        proxy = single_json(self.run(['inspect', container], capture_output=True).stdout)
        environment = dict(value.split('=', 1) for value in proxy['Config']['Env'])
        socket = Path(environment.get('SANDBOX_PROXY_SOCKET', '/run/sandbox-proxy/socket'))
        mounts = [mount for mount in proxy['Mounts'] if mount['Type'] == 'volume' and
                  socket.is_relative_to(Path(mount['Destination']))]
        if len(mounts) != 1:
            raise RuntimeError('proxy socket must belong to one owned volume')
        mount = mounts[0]
        arguments = ['--interactive', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                     '--memory', '64m', '--pids-limit', '16', '--cpus', '0.25',
                     '--ulimit', 'nofile=64:64',
                     '--security-opt', 'no-new-privileges',
                     '--user', proxy['Config']['User'] or '0',
                     '--env', 'SANDBOX_PROXY_SOCKET=' + str(socket),
                     '--mount', f"type=volume,src={mount['Name']},dst={mount['Destination']},readonly",
                     '--entrypoint', '/trusted/bin/sandbox-proxy-forward']
        image = self.inspect_image(proxy['Image'])
        def interrupted(signum, _frame):
            for pending in signals:
                signal.signal(pending, signal.SIG_IGN)
            raise SystemExit(128 + signum)
        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        handlers = {signum: signal.signal(signum, interrupted) for signum in signals}
        try:
            with self.workload(image, 'codex-forward-' + uuid.uuid4().hex, arguments) as process:
                return process.wait()
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def ensure_public_network(self):
        self.verify()

    def create_relay_network(self, name, *, internal, owner=None):
        self.verify()
        if not re.fullmatch(r'[0-9a-f]{32}', owner or ''):
            raise RuntimeError('invalid Docker relay owner')
        bridge = ('csl' if internal else 'cse') + hashlib.sha256(name.encode()).hexdigest()[:10]
        arguments = ['network', 'create', '--label', 'dev.codex.relay-owner=' + owner,
                     '--opt', 'com.docker.network.bridge.name=' + bridge]
        if internal:
            arguments += ['--internal']
        self.run([*arguments, name], stdout=subprocess.DEVNULL)

    def relay_owner(self, name):
        network = single_json(self.run(['network', 'inspect', name], capture_output=True).stdout)
        return network.get('Labels', {}).get('dev.codex.relay-owner')

    def initialize_volume(self, name, uid, gid, owner):
        self.run(['volume', 'create', '--label', 'dev.codex.volume-owner=' + owner, name],
                 stdout=subprocess.DEVNULL)
        volume = single_json(self.run(['volume', 'inspect', name], capture_output=True).stdout)
        if volume.get('Labels', {}).get('dev.codex.volume-owner') != owner:
            raise RuntimeError('refusing to initialize another creator\'s volume')
        path = Path(volume['Mountpoint'])
        if not path.is_absolute() or path.name != '_data' or path.parent.name != name:
            raise RuntimeError('unexpected Docker volume mountpoint')
        prefix = ['dockerd-rootless-setuptool.sh', 'nsenter', '--']
        self.guest([*prefix, 'touch', str(path / '.codex-initialized')], timeout=30)
        self.guest([*prefix, 'chown', f'{uid}:{gid}', str(path)], timeout=30)
