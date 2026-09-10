"""Rootless Docker operations through the owned Lima-forwarded engine socket."""

import hashlib
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import quote

from lima.docker_api import inspect as inspect_docker
from lima.docker_host import DockerHost
from lima.docker_client import verify_buildx, docker_client
from sandbox_runtime import VMRuntime, Image, RuntimeError, chain_id, digest, single_json, PROXY_ENV


class BuildError(subprocess.CalledProcessError):
    """BuildKit already printed diagnostics; retain argv only for programmatic inspection."""

    def __str__(self):
        return f'sandbox image build failed (exit {self.returncode}); see BuildKit output above'


def stop_build(process):
    """Drain the owned Buildx group even after its Docker wrapper exits."""
    def running():
        listing = subprocess.run(['ps', '-axo', 'pgid=,stat='], check=True,
                                 capture_output=True, text=True, timeout=5).stdout
        return any(fields[0] == str(process.pid) and not fields[1].startswith('Z')
                   for line in listing.splitlines() if len(fields := line.split()) == 2)
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not running():
            break
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + 3
        while running() and time.monotonic() < deadline:
            time.sleep(0.05)
    process.wait(timeout=5)
    if running():
        raise RuntimeError('Buildx processes did not stop; retain build diagnostics')


class Docker(VMRuntime):
    provider = 'lima-docker'
    host_address = 'host.lima.internal'
    nonrecursive_bind = 'bind-recursive=disabled'

    def __init__(self, state, *, recovery=False):
        self.host = DockerHost(state)
        self.record = self.host.record()
        self.recovery = recovery
        if self.record['phase'] != 'ready':
            raise RuntimeError('Docker prototype setup is incomplete')
        self.verify_identity()
        if not recovery:
            self.verify()

    def verify_identity(self):
        """Recovery needs the same engine, even when its admission policy is broken."""
        machine = self.host.machine(self.record)
        if self.record['socket'] != str(Path(machine['dir']) / 'sock/docker.sock'):
            raise RuntimeError('Docker socket differs from recorded VM')
        info = inspect_docker(self.record['socket'], '/info', ['docker', 'info'])
        if info['ID'] != self.record['engine_id'] or 'name=rootless' not in info['SecurityOptions']:
            raise RuntimeError('Docker engine identity changed; refusing recovery')

    def argv(self, arguments, *, cwd=None):
        # Both verification paths check the VM; do not query limactl twice.
        cleanup = (arguments[0] in ('inspect', 'ps', 'info', 'wait', 'rm', 'kill', 'stop') or
                   tuple(arguments[:2]) in (('container', 'ls'), ('network', 'ls'), ('network', 'inspect'),
                                           ('network', 'rm'), ('volume', 'ls'), ('volume', 'inspect'), ('volume', 'rm')))
        if cleanup:
            self.verify_identity()
        elif self.recovery:
            raise RuntimeError('Docker recovery permits inspection and cleanup only')
        else:
            self.verify()
        return self.client_argv(arguments)

    def client_argv(self, arguments):
        ambient = (*PROXY_ENV, 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
                   'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'DOCKER_API_VERSION',
                   'BUILDX_BUILDER', 'BUILDX_CONFIG', 'BUILDKIT_HOST', 'BUILDX_BAKE_FILE_RELATIVE_PATHS',
                   'DOCKER_CLI_PLUGIN_ORIGINAL_CLI_COMMAND', 'DOCKER_CLI_PLUGIN_SOCKET')
        environment = ['/usr/bin/env', *['-u' + name for name in ambient]]
        if arguments[0] == 'buildx':
            # Invoke the recorded binary directly: Docker's plugin search can
            # otherwise select a Homebrew upgrade or an ambient plugin path.
            return [*environment, 'DOCKER_HOST=unix://' + self.record['socket'],
                    'DOCKER_CONFIG=' + str(self.host.state / 'client'),
                    'BUILDX_CONFIG=' + str(self.host.state / 'client/buildx-state'),
                    str(verify_buildx(self.host.state)), *arguments[1:]]
        return [*environment, docker_client(self.host.state, self.record),
                '--config', str(self.host.state / 'client'), '--host', 'unix://' + self.record['socket'],
                *arguments]

    def run(self, arguments, **kwargs):
        kwargs.setdefault('timeout', 30)
        return super().run(arguments, **kwargs)

    def image_metadata(self, reference):
        if self.recovery:
            raise RuntimeError('Docker recovery permits inspection and cleanup only')
        self.verify()
        return inspect_docker(self.record['socket'], '/images/' + quote(reference, safe='') + '/json',
                              ['docker', 'image', 'inspect', reference])

    def inspect_image(self, reference):
        raw = self.image_metadata(reference)
        config = digest(raw['Id'])
        candidates = raw.get('RepoDigests') or []
        if '@' in reference:
            name, content = reference.rsplit('@', 1)
            repository = name.rsplit(':', 1)[0] if ':' in name.rsplit('/', 1)[-1] else name
            if repository + '@' + content not in candidates:
                raise RuntimeError('Docker image reference differs from its repository digest')
            immutable = reference
        elif candidates:
            repository = reference.rsplit(':', 1)[0] if ':' in reference.rsplit('/', 1)[-1] else reference
            matching = [candidate for candidate in candidates if candidate.rsplit('@', 1)[0] == repository]
            immutable = sorted(matching or candidates)[0]
            # BuildKit's local resolver needs the tag as well as the digest.
            # The digest still pins content if that tag later moves.
            repository, content = immutable.rsplit('@', 1)
            tags = [tag for tag in raw.get('RepoTags', []) if tag.rsplit(':', 1)[0] == repository]
            if tags:
                immutable = (reference if reference in tags else sorted(tags)[0]) + '@' + content
        else:
            raise RuntimeError('Docker image has no repository digest; rebuild with sandbox-image')
        content = digest(immutable.rsplit('@', 1)[1])
        return Image(immutable, content, config, chain_id(raw['RootFS']['Layers']))

    def inspect_container(self, container):
        self.verify_identity()
        return inspect_docker(self.record['socket'], '/containers/' + quote(container, safe='') + '/json',
                              ['docker', 'inspect', container])

    def builder_image(self, reference):
        if '@sha256:' not in reference and not re.fullmatch(r'sha256:[0-9a-f]{64}', reference):
            raise RuntimeError('Docker builders must return an immutable image ID or repository digest')
        return self.inspect_image(reference).reference

    def builder_environment(self):
        # Existing builders own their cache keys and call `docker` themselves.
        # Route those calls to this engine, not the host's Podman alias.
        return {**os.environ, 'CODEX_SANDBOX_RUNTIME': self.provider,
                'CODEX_SANDBOX_DOCKER_STATE': str(self.host.state),
                'PATH': str(Path(__file__).resolve().parent / 'builder-bin') + os.pathsep + os.environ['PATH']}

    def builder_arguments(self, arguments):
        arguments = list(arguments)
        for index, argument in enumerate(arguments):
            # Podman accepts a local config ID in FROM; BuildKit interprets it
            # as docker.io/library/sha256. Preserve the builder's BASE_IMAGE
            # contract using the recorded engine's tag plus manifest digest.
            prefix = '--build-arg=BASE_IMAGE=' if argument.startswith('--build-arg=') else 'BASE_IMAGE='
            if (argument.startswith(prefix) and
                    (prefix.startswith('--') or index > 0 and arguments[index - 1] == '--build-arg')):
                value = argument.removeprefix(prefix)
                if re.fullmatch(r'sha256:[0-9a-f]{64}', value):
                    arguments[index] = prefix + self.builder_image(value)
        return arguments

    def run_builder(self, command, *, cwd=None, capture=True):
        """Own the executable builder and all of its children until completion."""
        environment = {**self.builder_environment(), 'CODEX_SANDBOX_BUILDER_GROUP': '1'}
        process = subprocess.Popen(command, cwd=cwd, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else sys.stderr,
                                   text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=1800)
            if process.returncode:
                stop_build(process)
            return subprocess.CompletedProcess(command, process.returncode, stdout)
        except BaseException:
            handlers = ({signum: signal.signal(signum, signal.SIG_IGN)
                         for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
                        if threading.current_thread() is threading.main_thread() else {})
            try:
                stop_build(process)
            finally:
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()

    def run_builders(self, builders):
        """Supervise independent image builders on the signal-owning thread."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('image builders require the signal-owning thread')
        environment = {**self.builder_environment(), 'CODEX_SANDBOX_BUILDER_GROUP': '1'}
        pending = iter(builders.items())
        active = {}
        owned = []
        results = {}
        deadline = time.monotonic() + 1800
        with selectors.DefaultSelector() as selector:
            try:
                while len(results) < len(builders):
                    while len(active) < 4:
                        item = next(pending, None)
                        if item is None:
                            break
                        name, (command, cwd) = item
                        process = subprocess.Popen(command, cwd=cwd, env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, start_new_session=True)
                        owned.append(process)
                        active[name] = (process, bytearray(), command)
                        selector.register(process.stdout, selectors.EVENT_READ, name)
                    for key, _ in selector.select(timeout=0.01):
                        chunk = os.read(key.fd, 65536)
                        if chunk:
                            active[key.data][1].extend(chunk)
                        else:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    for name, (process, output, command) in list(active.items()):
                        status = process.poll()
                        if status is None:
                            continue
                        if status:
                            raise BuildError(status, command)
                        # A successful wrapper may leave a child writing its
                        # reference. Like communicate(), wait for pipe EOF too.
                        if not process.stdout.closed:
                            continue
                        stdout = output.decode(process.stdout.encoding).replace('\r\n', '\n').replace('\r', '\n')
                        results[name] = subprocess.CompletedProcess(command, status, stdout)
                        del active[name]
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired('sandbox image builders', 1800)
                return results
            except BaseException:
                handlers = {signum: signal.signal(signum, signal.SIG_IGN)
                            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
                try:
                    for process in owned:
                        try:
                            stop_build(process)
                        except (OSError, ValueError, subprocess.SubprocessError) as error:
                            print(f'Buildx cleanup incomplete: {error}', file=sys.stderr)
                finally:
                    for signum, handler in handlers.items():
                        signal.signal(signum, handler)
                raise
            finally:
                for process in owned:
                    process.stdout.close()

    @contextmanager
    def build_output(self):
        # Executable builders can run concurrently. Only an actual build owns
        # the native renderer; cache-key calculation and image lookup stay parallel.
        with (self.host.state / 'build-output.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def build(self, tag, dockerfile, context, *, build_args=(), target=None):
        self.verify()
        arguments = ['buildx', 'build', '--builder', 'default', '--load', '--provenance=false',
                     '--file', str(dockerfile), '--tag', tag]
        for value in build_args:
            arguments += ['--build-arg', value]
        if target:
            arguments += ['--target', target]
        with self.build_output():
            command = self.argv(self.builder_arguments([*arguments, str(context)]))
            if os.environ.get('CODEX_SANDBOX_BUILDER_GROUP') == '1':
                # The enclosing executable builder owns this process group.
                # A nested session would let Buildx escape its cancellation.
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=sys.stderr, timeout=1800)
            else:
                result = self.run_builder(command, capture=False)
            if result.returncode:
                raise BuildError(result.returncode, command)
        return self.resolve_image(tag)

    def bake_targets(self, definition, targets, *, cwd):
        """Let Buildx resolve HCL variables, inheritance, and dependencies."""
        result = self.run(['buildx', 'bake', '--file', str(definition), '--print', *targets],
                          cwd=cwd, capture_output=True)
        return json.loads(result.stdout)['target']

    def bake(self, targets, *, cwd=None):
        self.verify()
        with tempfile.TemporaryDirectory(prefix='bake-', dir=self.host.state / 'scratch') as directory:
            definition = Path(directory) / 'build.json'
            metadata = Path(directory) / 'result.json'
            definition.write_text(json.dumps({'target': targets, 'group': {'default': {'targets': list(targets)}}}))
            reads = set()
            for target in targets.values():
                context = target.get('context', '.')
                if '://' not in context and not context.startswith('git@'):
                    context = (Path(cwd or Path.cwd()) / context).resolve()
                    reads.update((str(context), str((context / target.get('dockerfile', 'Dockerfile')).parent)))
                for value in target.get('contexts', {}).values():
                    if not value.startswith(('target:', 'docker-image:', 'git@')) and '://' not in value:
                        reads.add(str((Path(cwd or Path.cwd()) / value).resolve()))
            command = self.argv(['buildx', 'bake', '--builder', 'default', '--file', str(definition),
                                 *['--allow=fs.read=' + path for path in sorted(reads)],
                                 '--set=*.output=type=docker', '--provenance=false', '--metadata-file', str(metadata)])
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sys.stderr,
                                       start_new_session=True, cwd=cwd)
            try:
                status = process.wait(timeout=1800)
                if status:
                    raise BuildError(status, command)
                return json.loads(metadata.read_text())
            except BaseException:
                # The Docker CLI spawns a Buildx plugin. Cancellation owns both
                # processes, not just the wrapper returned by Popen.
                handlers = ({signum: signal.signal(signum, signal.SIG_IGN)
                             for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
                            if threading.current_thread() is threading.main_thread() else {})
                try:
                    try:
                        stop_build(process)
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        print(f'Buildx cleanup incomplete: {error}', file=sys.stderr)
                finally:
                    for signum, handler in handlers.items():
                        signal.signal(signum, handler)
                raise

    def workload_argv(self, image, arguments, command=(), *, cwd=None, operation='run'):
        return self.argv([operation, '--pull=never', *arguments, image.config, *command], cwd=cwd)

    def agent_command(self, image, arguments):
        config = self.image_metadata(image)['Config']
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
        if not re.fullmatch(r'[0-9a-f]{32}', owner or ''):
            raise RuntimeError('invalid Docker relay owner')
        bridge = ('csl' if internal else 'cse') + hashlib.sha256(name.encode()).hexdigest()[:10]
        arguments = ['network', 'create', '--label', 'dev.codex.relay-owner=' + owner,
                     '--opt', 'com.docker.network.bridge.name=' + bridge]
        if internal:
            arguments += ['--internal']
        # run/argv verifies immediately before creation; an earlier check here
        # would repeat the same VM and service audit for this one operation.
        self.run([*arguments, name], stdout=subprocess.DEVNULL)
        # Docker can change bridge traversal without changing its service epoch,
        # so the cached verification receipt cannot cover network creation.
        if self.record.get('firewall') == 'nftables':
            self.guest(['python3', '/usr/local/share/codex-sandbox/docker-policy.py', 'check-bridges'])

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
