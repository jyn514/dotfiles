#!/usr/bin/env python3

from contextlib import redirect_stderr, redirect_stdout
import ctypes
import io
import json
import os
import runpy
import signal
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_resolver
import owned_images
from sandbox_runtime import ContainerRuntime, Image, Lima, VMRuntime, RuntimeError as SandboxRuntimeError
from docker_runtime import Docker


FIXTURE = Path(__file__).parent / "fixtures" / "resolver_protocol.py"


def bounded_fixture(mode, pidfile):
    """Finite native producer: even broken supervision cannot leave live work."""
    pending = mode.startswith('pending-') or mode == 'nonreading-request'
    if pending:
        # Break circular pipe waits even when testing the original implementation.
        signal.alarm(3)
        request = None
    else:
        request = json.load(sys.stdin)
    if mode in {'stdout-overflow', 'stderr-overflow', 'closed-pipes', 'exited-parent',
                'pending-stdout-overflow', 'pending-stderr-overflow', 'nonreading-request'}:
        child = os.fork()
        if child == 0:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            Path(pidfile).write_text(str(os.getpid()))
            if mode in {'closed-pipes', 'nonreading-request'}:
                os.close(1)
                os.close(2)
            time.sleep(3)
            os._exit(0)
        deadline = time.monotonic() + 1
        while not Path(pidfile).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    if mode == 'nonreading-request':
        os.close(1)
        os.close(2)
        time.sleep(3)
        return
    if pending:
        def write_all(fd, data):
            while data:
                data = data[os.write(fd, data):]

        if mode == 'pending-success':
            # Both exceed pipe capacity before stdin is read. A blocking write
            # by the supervisor would deadlock against this legitimate producer.
            write_all(1, b' ' * (128 * 1024))
            write_all(2, b'd' * (128 * 1024))
            received = sys.stdin.buffer.read()
            assert received.endswith(b'\n') and received.count(b'\n') == 1
            json.loads(received)
            write_all(1, json.dumps({'received': received.decode()}).encode())
        elif mode == 'pending-stdout-overflow':
            write_all(1, b'x' * (1024 * 1024 + 1))
        elif mode == 'pending-stderr-overflow':
            write_all(2, b'd' * (8 * 1024 * 1024 + 1))
        return
    if mode == 'early-eof-success':
        os.write(1, json.dumps({'version': 1, 'images': {
            name: 'sha256:' + 'a' * 64 for name in request['images']}}).encode())
        os.close(1)
        os.close(2)
        time.sleep(0.05)
        os._exit(0)
    if mode == 'closed-pipes':
        os.close(1)
        os.close(2)
        time.sleep(3)
        return
    if mode == 'unicode':
        data = ('☃' * 30000).encode()
        while data:
            data = data[os.write(2, data):]
    if mode in {'stderr-overflow', 'limits', 'nonzero'}:
        size = 8 * 1024 * 1024 + (mode == 'stderr-overflow')
        # A full stderr pipe must not block the stdout reader.
        chunk = b'd' * 65536
        while size:
            written = os.write(2, chunk[:size])
            size -= written
    if mode == 'stdout-overflow':
        sys.stdout.write('x' * (1024 * 1024 + 1))
    else:
        output = json.dumps({'version': 1, 'images': {
            name: 'sha256:' + 'a' * 64 for name in request['images']}})
        sys.stdout.write(output + ' ' * (1024 * 1024 - len(output)))
    if mode == 'nonzero':
        sys.exit(23)


def helper_fixture(reference, receipt, mode):
    assert sys.stdin.buffer.read() == b''
    Path(receipt).write_text(json.dumps({
        'provider': os.environ['CODEX_SANDBOX_RUNTIME'],
        'state': os.environ.get('CODEX_SANDBOX_LIMA_STATE'),
        'group': os.environ['CODEX_SANDBOX_BUILDER_GROUP'],
        'cwd': str(Path.cwd()),
        'pid': os.getpid(),
    }))
    # One diagnostic is one pipe write. With PYTHONUNBUFFERED, print splits
    # text and newline, letting independent helpers interleave those writes.
    os.write(2, b'helper diagnostic\n')
    sys.stdout.write(reference + '\r\n')
    if mode.startswith('overlap-') or mode == 'fail-peer':
        Path(receipt).with_suffix('.ready').touch()
        peer = Path(receipt).parent / (
            'second.ready' if mode == 'overlap-first' else
            'first.ready' if mode == 'overlap-second' else 'waiting.ready')
        deadline = time.monotonic() + 1
        while not peer.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not peer.exists() or mode == 'fail-peer':
            sys.exit(23)
    if mode in {'waiting-eof', 'waiting-pipes'}:
        sys.stdout.flush()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        pidfile = Path(receipt).with_suffix('.child.pid')
        if os.fork() == 0:
            if mode == 'waiting-eof':
                os.close(1)
                os.close(2)
            pidfile.write_text(str(os.getpid()))
            time.sleep(3)
            os._exit(0)
        if mode == 'waiting-eof':
            os.close(1)
            os.close(2)
        deadline = time.monotonic() + 1
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        Path(receipt).with_suffix('.ready').touch()
        time.sleep(3)
    if mode == 'multiline':
        print(reference)
    if mode == 'nonzero':
        sys.exit(23)
    if mode == 'timeout':
        time.sleep(3)


class NativePreparationTest(unittest.TestCase):
    def test_empty_preparation_does_not_call_engine_or_builder_apis(self):
        for runtime_type in (ContainerRuntime, VMRuntime, Docker):
            with self.subTest(runtime=runtime_type.__name__):
                runtime = mock.Mock(spec=runtime_type, provider=runtime_type.provider)
                prepared = image_resolver.prepare_launch_images(
                    runtime, Path('/nonexistent-project'), {},
                    image_policy={'base': 'base', 'resolver': {
                        'kind': 'command', 'argv': ['/nonexistent-resolver']}})
                self.assertEqual(image_resolver.PreparedImages(None, None, {}), prepared)
                self.assertEqual([], runtime.method_calls)

    def test_executable_owned_helpers_use_real_non_docker_interfaces_and_inspection(self):
        for runtime_type in (ContainerRuntime, Lima):
            for mode in ('valid', 'multiline', 'nonzero', 'wrong-platform', 'timeout'):
                with self.subTest(provider=runtime_type.provider, mode=mode), \
                        tempfile.TemporaryDirectory() as directory:
                    root = Path(directory).resolve()
                    runtime = object.__new__(runtime_type)
                    runtime.host = SimpleNamespace(state=root / 'lima-state')
                    content = 'sha256:' + 'a' * 64
                    reference = ('localhost/codex-sandbox:sha256-' + 'a' * 64 + '@' + content
                                 if runtime_type is Lima else content)
                    platform = 'amd64' if mode == 'wrong-platform' else 'arm64'
                    calls = []

                    def engine_run(arguments, **_kwargs):
                        calls.append(arguments)
                        if arguments == ['info', '--format', '{{.OSType}}/{{.Architecture}}']:
                            output = 'linux/arm64\n'
                        elif arguments[:2] == ['image', 'inspect']:
                            if runtime_type is Lima:
                                self.assertEqual(['image', 'inspect', '--mode=native', reference], arguments)
                                image = {
                                    'Image': {'Name': reference, 'Target': {'size': 1,
                                        'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                        'digest': content}},
                                    'ImageConfigDesc': {'digest': 'sha256:' + 'c' * 64},
                                    'ImageConfig': {'os': 'linux', 'architecture': platform,
                                        'rootfs': {'diff_ids': ['sha256:' + 'd' * 64]}},
                                }
                            else:
                                self.assertEqual(['image', 'inspect', reference], arguments)
                                image = {'Id': content, 'Os': 'linux', 'Architecture': platform,
                                         'RootFS': {'Layers': ['sha256:' + 'd' * 64]}}
                            output = json.dumps([image])
                        else:
                            self.fail(f'unexpected engine acquisition or build: {arguments}')
                        return subprocess.CompletedProcess(arguments, 0, output)

                    runtime.run = engine_run
                    receipt = root / 'helper.json'
                    helper = root / 'owned-helper'
                    helper.write_text('#!/usr/bin/env python3\nimport runpy\n' +
                        f"runpy.run_path({str(Path(__file__).resolve())!r})['helper_fixture'](" +
                        f'{reference!r}, {str(receipt)!r}, {mode!r})\n')
                    helper.chmod(0o755)
                    diagnostics = io.StringIO()
                    machine_output = io.StringIO()
                    policy = {'base': 'base', 'resolver': {
                        'kind': 'command', 'argv': ['/nonexistent-resolver']}}
                    with mock.patch.dict(owned_images.COMMANDS, {str(helper): 'auth'}), \
                            mock.patch.object(image_resolver, 'TIMEOUT', 0.5), \
                            mock.patch.object(image_resolver, 'KILL_TIMEOUT', 0.1), \
                            redirect_stderr(diagnostics), redirect_stdout(machine_output):
                        if mode in {'multiline', 'nonzero'}:
                            with self.assertRaisesRegex(image_resolver.ResolverError,
                                                        'one immutable image hash'):
                                image_resolver.prepare_launch_images(runtime, root, {},
                                    auth_builder=([str(helper)], root), image_policy=policy)
                            self.assertEqual([], calls)
                        elif mode == 'timeout':
                            with self.assertRaises(subprocess.TimeoutExpired):
                                image_resolver.prepare_launch_images(runtime, root, {},
                                    auth_builder=([str(helper)], root), image_policy=policy)
                            self.assertEqual([], calls)
                        elif mode == 'wrong-platform':
                            with self.assertRaisesRegex(SandboxRuntimeError, 'linux/amd64.*linux/arm64'):
                                image_resolver.prepare_launch_images(runtime, root, {},
                                    auth_builder=([str(helper)], root), image_policy=policy)
                            self.assertTrue(calls)
                        else:
                            prepared = image_resolver.prepare_launch_images(runtime, root, {},
                                auth_builder=([str(helper)], root), image_policy=policy)
                            self.assertEqual(reference, prepared.auth)
                            self.assertEqual({}, prepared.proxies)
                            self.assertTrue(any(call[:2] == ['image', 'inspect'] for call in calls))
                            self.assertIn(['info', '--format', '{{.OSType}}/{{.Architecture}}'], calls)
                    observed = json.loads(receipt.read_text())
                    pid = observed.pop('pid')
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                    self.assertEqual({'provider': runtime.provider,
                        'state': str(runtime.host.state) if runtime_type is Lima else None,
                        'group': '1', 'cwd': str(root)}, observed)
                    self.assertEqual('helper diagnostic\n', diagnostics.getvalue())
                    self.assertEqual('', machine_output.getvalue())


class ResolverSupervisionTest(unittest.TestCase):
    def setUp(self):
        # Linux test containers may have a PID 1 that does not reap orphans.
        # Own fixture grandchildren so tests leave neither live work nor zombies.
        if sys.platform.startswith('linux'):
            libc = ctypes.CDLL(None, use_errno=True)
            previous = ctypes.c_int()
            self.assertEqual(0, libc.prctl(37, ctypes.byref(previous), 0, 0, 0))
            self.assertEqual(0, libc.prctl(36, 1, 0, 0, 0))
            self.addCleanup(libc.prctl, 36, previous.value, 0, 0, 0)

    def reap_fixture(self, pidfile):
        if not pidfile.exists():
            return
        pid = int(pidfile.read_text())
        try:
            # Fixture work is finite even against the original broken resolver.
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass  # Non-Linux init or an earlier assertion already reaped it.

    def fixture_command(self, mode):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.pidfile = Path(directory) / 'child.pid'
        self.addCleanup(self.reap_fixture, self.pidfile)
        self.runtime = Runtime()
        self.diagnostics = io.StringIO()
        self.machine_output = io.StringIO()
        self.enterContext(redirect_stderr(self.diagnostics))
        self.enterContext(redirect_stdout(self.machine_output))
        self.enterContext(mock.patch.object(image_resolver, 'TIMEOUT', 1))
        self.enterContext(mock.patch.object(image_resolver, 'KILL_TIMEOUT', 0.1))
        return [sys.executable, str(Path(__file__).resolve()), '--bounded-fixture', mode,
                str(self.pidfile)]

    def run_resolver(self, mode):
        command = self.fixture_command(mode)
        return image_resolver.resolve_command(self.runtime, Path.cwd(), command, {'base'})

    def admitted_large_request(self, command):
        parser = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'sandbox-proxies.py'))
        names = ['image-' + str(index).zfill(5) + '-' + 'a' * 51 for index in range(2048)]
        declaration = {
            'version': 2,
            'images': {'resolver': {'kind': 'command', 'argv': command}, 'base': 'base'},
            'commands': {name: {'image': name, 'argv': ['test-command'], 'workdir': '.',
                                'network': False, 'mounts': []} for name in names},
        }
        path = self.pidfile.parent / 'proxy-commands.json'
        path.write_text(json.dumps(declaration))
        manifest = parser['load_manifest_file'](path)
        requested = {item['image-target'] for item in manifest['commands'].values()}
        requested.add(manifest['images']['base'])
        self.assertEqual(2048, len(manifest['commands']))
        request = {'version': 1, 'operation': 'resolve',
                   'engine': {'provider': self.runtime.provider,
                              'platform': self.runtime.build_platform()},
                   'images': sorted(requested)}
        encoded = (json.dumps(request, separators=(',', ':'), sort_keys=True) + '\n').encode()
        return requested, encoded

    def prepare_helper_pair(self, first_mode, second_mode):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory).resolve()
        runtime = ContainerRuntime()
        runtime.verify_builder_image = mock.Mock(side_effect=lambda reference:
            Image(reference, reference, reference, reference))
        self.runtime = runtime
        self.diagnostics = io.StringIO()
        self.machine_output = io.StringIO()
        self.enterContext(redirect_stderr(self.diagnostics))
        self.enterContext(redirect_stdout(self.machine_output))
        self.enterContext(mock.patch.object(image_resolver, 'TIMEOUT', 2))
        self.enterContext(mock.patch.object(image_resolver, 'KILL_TIMEOUT', 0.1))
        modes = [('first', first_mode),
                 ('waiting' if second_mode.startswith('waiting-') else 'second', second_mode)]
        self.receipts = []
        commands = []
        for index, (name, mode) in enumerate(modes):
            receipt = root / (name + '.json')
            self.receipts.append(receipt)
            helper = root / name
            reference = 'sha256:' + str(index + 1) * 64
            helper.write_text('#!/usr/bin/env python3\nimport runpy\n' +
                f"runpy.run_path({str(Path(__file__).resolve())!r})['helper_fixture'](" +
                f'{reference!r}, {str(receipt)!r}, {mode!r})\n')
            helper.chmod(0o755)
            commands.append([str(helper)])
        if second_mode.startswith('waiting-'):
            self.pidfile = self.receipts[1].with_suffix('.child.pid')
            self.addCleanup(self.reap_fixture, self.pidfile)
        return image_resolver.prepare_launch_images(runtime, root,
            {'helper': {'image-command': commands[1]}}, auth_builder=(commands[0], root))

    def assert_helper_leaders_joined(self):
        for receipt in self.receipts:
            with self.assertRaises(ProcessLookupError):
                os.kill(json.loads(receipt.read_text())['pid'], 0)

    def test_independent_executable_helpers_overlap_and_each_is_verified_once(self):
        prepared = self.prepare_helper_pair('overlap-first', 'overlap-second')
        self.assertEqual('sha256:' + '1' * 64, prepared.auth)
        self.assertEqual({'helper': 'sha256:' + '2' * 64}, prepared.proxies)
        self.assertCountEqual(['sha256:' + '1' * 64, 'sha256:' + '2' * 64],
            [call.args[0] for call in self.runtime.verify_builder_image.call_args_list])
        self.assertEqual('helper diagnostic\n' * 2, self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())
        self.assert_helper_leaders_joined()

    def test_helper_failure_cancels_and_joins_peer_before_and_after_output_eof(self):
        for mode in ('waiting-pipes', 'waiting-eof'):
            with self.subTest(mode=mode):
                started = time.monotonic()
                with self.assertRaisesRegex(image_resolver.ResolverError, 'one immutable image hash'):
                    self.prepare_helper_pair('fail-peer', mode)
                # Peer has a 2s deadline and finite 3s work. Cancellation must
                # finish sooner, including when it is only waiting for exit.
                self.assertLess(time.monotonic() - started, 1.5)
                self.assert_helper_leaders_joined()
                self.assert_child_stopped()
                self.runtime.verify_builder_image.assert_not_called()
                self.assertEqual('helper diagnostic\n' * 2, self.diagnostics.getvalue())
                self.assertEqual('', self.machine_output.getvalue())

    def test_large_admitted_request_and_output_are_supervised_concurrently(self):
        command = self.fixture_command('pending-success')
        _, encoded = self.admitted_large_request(command)
        status, output = image_resolver._run(command, Path.cwd(), encoded, os.environ.copy())
        self.assertEqual(0, status)
        self.assertEqual(encoded.decode(), json.loads(output)['received'])
        self.assertTrue(output.startswith(b' ' * (128 * 1024)))
        self.assertEqual('d' * (128 * 1024), self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())

    def test_nonreading_resolver_cannot_bypass_deadline_with_large_admitted_request(self):
        command = self.fixture_command('nonreading-request')
        requested, _ = self.admitted_large_request(command)
        with self.assertRaises(subprocess.TimeoutExpired):
            image_resolver.resolve_command(self.runtime, Path.cwd(), command, requested)
        self.assert_child_stopped()
        self.assertEqual([], self.runtime.inspected)
        self.assertEqual('', self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())

    def test_output_overflow_cancels_descendants_while_large_request_is_pending(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                command = self.fixture_command('pending-' + stream + '-overflow')
                _, encoded = self.admitted_large_request(command)
                with self.assertRaisesRegex(image_resolver.ResolverError, stream + ' exceeds'):
                    image_resolver._run(command, Path.cwd(), encoded, os.environ.copy())
                self.assert_child_stopped()
                self.assertLessEqual(len(self.diagnostics.getvalue()), 8 * 1024 * 1024)
                self.assertEqual('', self.machine_output.getvalue())

    def assert_child_stopped(self):
        pid = int(self.pidfile.read_text())
        # Confirm cancellation, then reap the adopted fixture grandchild.
        state = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic() + 0.5
        while state.exists():
            if state.read_text().split(') ', 1)[1].split()[0] == 'Z':
                self.reap_fixture(self.pidfile)
                return
            if time.monotonic() >= deadline:
                self.fail(f'resolver descendant {pid} is still running')
            time.sleep(0.01)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_exact_limits_are_valid_and_channels_stay_separate(self):
        self.assertEqual({'base'}, set(self.run_resolver('limits')))
        self.assertEqual('d' * (8 * 1024 * 1024), self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())

    def test_multibyte_diagnostics_are_not_corrupted_at_pipe_read_boundaries(self):
        self.assertEqual({'base'}, set(self.run_resolver('unicode')))
        self.assertEqual('☃' * 30000, self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())

    def test_either_overflow_cancels_owned_descendants(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                with self.assertRaisesRegex(image_resolver.ResolverError, stream + ' exceeds'):
                    self.run_resolver(stream + '-overflow')
                self.assert_child_stopped()
                self.assertLessEqual(len(self.diagnostics.getvalue()), 8 * 1024 * 1024)
                self.assertEqual('', self.machine_output.getvalue())
                self.assertEqual([], self.runtime.inspected)

    def test_nonzero_reports_bounded_diagnostics_once_without_inspection(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, 'status 23'):
            self.run_resolver('nonzero')
        self.assertEqual('d' * (8 * 1024 * 1024), self.diagnostics.getvalue())
        self.assertEqual('', self.machine_output.getvalue())
        self.assertEqual([], self.runtime.inspected)

    def test_resolver_can_close_pipes_then_exit_within_deadline(self):
        self.assertEqual({'base'}, set(self.run_resolver('early-eof-success')))
        self.assertEqual('', self.diagnostics.getvalue())

    def test_timeout_kills_descendant_after_resolver_parent_exits(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_resolver('exited-parent')
        self.assert_child_stopped()

    def test_timeout_remains_active_after_both_output_pipes_close(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_resolver('closed-pipes')
        self.assert_child_stopped()


class Runtime:
    provider = "lima-docker"

    def __init__(self):
        self.inspected = []

    def build_platform(self):
        return "linux/test"

    def upstream_image(self, reference):
        return reference + '@sha256:' + 'e' * 64

    def builder_environment(self):
        return os.environ.copy()

    def builder_image(self, reference):
        self.inspected.append(reference)
        return "verified:" + reference

    def inspect_image(self, reference):
        return Image(reference, reference, reference, reference)

    def verify_builder_image(self, reference):
        return self.inspect_image(self.builder_image(reference))


class ImageResolverTest(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, HOME=home))
        self.pi_marker = Path(home) / '.local/share/pi/node/.source-revision'
        self.pi_marker.parent.mkdir(parents=True)
        self.pi_marker.write_text('a' * 40 + '\n')
        cache = Path(home) / 'image-cache'
        cache.mkdir(mode=0o700)
        self.enterContext(mock.patch('bake._cache_directory', return_value=cache))
        self.jj_image = Image('jj@sha256:' + '9' * 64, 'jj', 'jj-config', 'jj-rootfs')
        self.jj_resolver = self.enterContext(mock.patch('bake.resolve', return_value={'jj': self.jj_image.reference}))

    def test_installed_pi_commit_selects_build_argument_and_cached_image(self):
        runtime = Runtime()
        images = {}
        builds = []
        runtime.image_if_available = images.get

        def build(tag, dockerfile, context, *, build_args):
            image = Image(tag + '@sha256:' + 'd' * 64, tag, 'config', 'rootfs')
            images[tag] = image
            builds.append(build_args)
            return image

        runtime.build = build
        first = owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertIn('PI_REVISION=' + 'a' * 40, builds[-1])
        self.assertEqual(first, owned_images.resolve_agent(runtime, 501, 20, 'base'))
        self.assertEqual(1, len(builds))

        self.pi_marker.write_text('b' * 40 + '\n')
        second = owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertNotEqual(first, second)
        self.assertEqual(2, len(builds))
        self.assertIn('PI_REVISION=' + 'b' * 40, builds[-1])
        self.assertEqual(second, owned_images.resolve_agent(runtime, 501, 20, 'base'))
        self.assertEqual(2, len(builds))

    def test_guest_uses_resolved_proxy_artifact_and_invalidates_cache_when_it_changes(self):
        runtime = Runtime()
        images = {}
        builds = []
        runtime.image_if_available = images.get

        def build(tag, dockerfile, context, *, build_args):
            builds.append((build_args, dockerfile.read_text()))
            image = Image(tag + '@sha256:' + 'd' * 64, tag, tag, 'rootfs')
            images[tag] = image
            return image

        runtime.build = build
        first = owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertIn('JJ_IMAGE=' + self.jj_image.reference, builds[-1][0])
        self.assertIn('FROM ' + self.jj_image.reference + ' AS jj', builds[-1][1])
        self.assertEqual(first, owned_images.resolve_agent(runtime, 501, 20, 'base'))
        self.assertEqual(1, len(builds))
        replacement = Image('jj@sha256:' + '8' * 64, 'jj-new', 'jj-new-config', 'jj-rootfs')
        self.jj_resolver.return_value = {'jj': replacement.reference}
        second = owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertNotEqual(first, second)
        self.assertEqual(2, len(builds))
        self.assertIn('JJ_IMAGE=' + replacement.reference, builds[-1][0])

    def test_legacy_engines_share_owned_proxy_tag_without_docker_bake(self):
        for runtime_type in (ContainerRuntime, Lima):
            with self.subTest(provider=runtime_type.provider):
                runtime = object.__new__(runtime_type)
                images = {}
                builds = []
                runtime.image_if_available = images.get
                runtime.build_platform = lambda: 'linux/arm64'
                runtime.inspect_image = lambda reference: Image(reference, 'base', 'config', 'rootfs')
                runtime.upstream_image = lambda reference: reference + '@sha256:' + 'e' * 64

                def build(tag, dockerfile, context, *, build_args, no_cache=False):
                    self.assertTrue(dockerfile.is_file())
                    self.assertTrue(dockerfile.is_relative_to(context))
                    builds.append((tag, build_args, dockerfile.read_text(), no_cache))
                    image = Image('sha256:' + str(len(builds)) * 64, tag, tag, 'rootfs')
                    images[tag] = image
                    return image

                runtime.build = build
                guest = owned_images.resolve_agent(runtime, 501, 20, 'base')
                target = owned_images.declaration(['jj'])['target']['jj']
                self.assertEqual(target['tags'][0], builds[0][0])
                self.assertEqual([f'{name}={value}' for name, value in owned_images.jj_release_args().items()],
                                 builds[0][1])
                proxy = images[target['tags'][0]].reference
                self.assertIn('JJ_IMAGE=' + proxy, builds[1][1])
                self.assertIn('FROM ' + proxy + ' AS jj', builds[1][2])
                self.assertEqual(guest, owned_images.resolve_agent(runtime, 501, 20, 'base'))
                self.assertEqual(2, len(builds))
                self.jj_resolver.assert_not_called()
                self.assertEqual(proxy, owned_images.resolve_jj(runtime))
                owned_images.resolve_jj(runtime, operation='clean')
                self.assertTrue(builds[-1][3])

    def test_legacy_proxy_build_failure_stops_guest_composition(self):
        runtime = ContainerRuntime()
        runtime.image_if_available = lambda _tag: None
        runtime.inspect_image = lambda reference: Image(reference, 'base', 'config', 'rootfs')
        runtime.build = mock.Mock(side_effect=OSError('JJ build failed'))
        with self.assertRaisesRegex(OSError, 'JJ build failed'):
            owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertEqual(1, runtime.build.call_count)
        self.assertEqual([f'{name}={value}' for name, value in owned_images.jj_release_args().items()],
                         runtime.build.call_args.kwargs['build_args'])
        self.jj_resolver.assert_not_called()

    def test_proxy_build_failure_stops_guest_composition(self):
        runtime = Runtime()
        runtime.build = mock.Mock()
        self.jj_resolver.side_effect = OSError('JJ build failed')
        with self.assertRaisesRegex(OSError, 'JJ build failed'):
            owned_images.resolve_agent(runtime, 501, 20, 'base')
        runtime.build.assert_not_called()

    def test_missing_or_invalid_pi_metadata_stops_before_engine_work(self):
        for record in (None, b'', b'main\n', b'a' * 39, b'a' * 41,
                       b'g' * 40, b'a' * 40 + b'\ninjected', b'\xff'):
            with self.subTest(record=record):
                if record is None:
                    self.pi_marker.unlink()
                else:
                    self.pi_marker.write_bytes(record)
                runtime = mock.Mock()
                with self.assertRaisesRegex(ValueError, 'run mise run pi-install'):
                    owned_images.resolve_agent(runtime, 501, 20, 'base')
                self.assertEqual([], runtime.mock_calls)

    def test_build_keeps_the_commit_captured_before_host_metadata_changes(self):
        runtime = Runtime()
        runtime.image_if_available = lambda _tag: None
        inspect = runtime.inspect_image

        def inspect_and_update(reference):
            self.pi_marker.write_text('b' * 40 + '\n')
            return inspect(reference)

        runtime.inspect_image = inspect_and_update
        runtime.build = mock.Mock(return_value=Image('agent', 'agent', 'config', 'rootfs'))
        cache_key = owned_images.agent_cache_key
        with mock.patch.object(owned_images, 'agent_cache_key', wraps=cache_key) as key:
            owned_images.resolve_agent(runtime, 501, 20, 'base')
        self.assertEqual('a' * 40, key.call_args.args[4])
        self.assertIn('PI_REVISION=' + 'a' * 40,
                      runtime.build.call_args.kwargs['build_args'])

    def test_default_base_is_pulled_only_when_missing(self):
        for available in (False, True):
            with self.subTest(available=available):
                runtime = mock.Mock(provider='lima-docker')
                base = Image('sha256:' + 'a' * 64, 'base', 'config', 'rootfs')
                local = {owned_images.DEFAULT_BASE: base} if available else {}
                runtime.image_if_available.side_effect = lambda ref: local.get(ref)
                runtime.inspect_image.side_effect = lambda ref: local[ref]
                runtime.run.side_effect = lambda *args, **kwargs: local.update(
                    {owned_images.DEFAULT_BASE: base})
                runtime.build.return_value = Image('agent', 'agent', 'config', 'rootfs')
                with mock.patch('bake._capture'), mock.patch('bake._pin_dockerfile'), \
                        mock.patch.object(owned_images, 'agent_cache_key', return_value='key'):
                    self.assertEqual('agent', owned_images.resolve_agent(
                        runtime, 501, 20, owned_images.DEFAULT_BASE))
                self.assertEqual(0 if available else 1, runtime.run.call_count)
                if not available:
                    self.assertEqual(['pull', owned_images.DEFAULT_BASE], runtime.run.call_args.args[0])
                self.assertIn('BASE_IMAGE=' + base.reference, runtime.build.call_args.kwargs['build_args'])

    def test_default_base_selection_follows_launcher_authority(self):
        runtime = mock.Mock()
        runtime.bake.return_value = {}
        runtime.run_builders.return_value = {}
        with mock.patch.object(owned_images, 'DEFAULT_BASE', 'replacement:base'):
            prepared = image_resolver.prepare_launch_images(
                runtime, Path('/nonexistent-project'), {}, include_base=True)
        self.assertEqual('replacement:base', prepared.base)

    def test_default_base_pull_failure_stops_composition(self):
        runtime = mock.Mock()
        runtime.image_if_available.return_value = None
        runtime.run.side_effect = OSError('pull failed')
        with mock.patch('bake._capture'), self.assertRaisesRegex(OSError, 'pull failed'):
            owned_images.resolve_agent(runtime, 501, 20, owned_images.DEFAULT_BASE)
        runtime.build.assert_not_called()

    def test_missing_project_base_is_not_pulled(self):
        runtime = mock.Mock()
        runtime.inspect_image.side_effect = OSError('project base missing')
        with mock.patch('bake._capture'), self.assertRaisesRegex(OSError, 'project base missing'):
            owned_images.resolve_agent(runtime, 501, 20, 'sha256:' + 'b' * 64)
        runtime.run.assert_not_called()
        runtime.build.assert_not_called()

    def resolve(self, mode="valid", names={"base", "proxy"}):
        runtime = Runtime()
        previous = os.environ.get("RESOLVER_FIXTURE")
        os.environ["RESOLVER_FIXTURE"] = mode
        try:
            result = image_resolver.resolve_command(runtime, Path.cwd(), [sys.executable, str(FIXTURE)], names)
        finally:
            if previous is None:
                os.environ.pop("RESOLVER_FIXTURE", None)
            else:
                os.environ["RESOLVER_FIXTURE"] = previous
        return runtime, result

    def test_validates_complete_exact_result_then_inspects_images(self):
        runtime, result = self.resolve()
        self.assertEqual({"base", "proxy"}, set(result))
        self.assertEqual(2, len(runtime.inspected))

    def test_rejects_extra_name_before_inspection(self):
        runtime = Runtime()
        previous = os.environ.get("RESOLVER_FIXTURE")
        os.environ["RESOLVER_FIXTURE"] = "extra"
        try:
            with self.assertRaisesRegex(image_resolver.ResolverError, "exactly match"):
                image_resolver.resolve_command(runtime, Path.cwd(), [sys.executable, str(FIXTURE)], {"base"})
        finally:
            if previous is None:
                os.environ.pop("RESOLVER_FIXTURE", None)
            else:
                os.environ["RESOLVER_FIXTURE"] = previous
        self.assertEqual([], runtime.inspected)

    def test_rejects_duplicate_json_fields(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, "duplicate JSON field"):
            self.resolve("duplicate", {"base"})

    def test_bounds_stdout(self):
        with self.assertRaisesRegex(image_resolver.ResolverError, "stdout exceeds"):
            self.resolve("large", {"base"})

    def test_reports_nonzero_status_after_streaming_stderr(self):
        with self.assertRaisesRegex(
                image_resolver.ResolverError,
                "status 23; see resolver output above",
        ):
            self.resolve("error", {"base"})

    def test_agent_composition_builds_only_for_a_missing_complete_identity(self):
        runtime = type("AgentRuntime", (), {})()
        runtime.provider = "lima-docker"
        runtime.build_platform = lambda: "linux/arm64"
        runtime.upstream_image = lambda reference: reference + "@sha256:" + "e" * 64
        runtime.inspect_image = lambda reference: Image(
            reference, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )
        runtime.image_if_available = lambda _tag: None
        built = []
        runtime.build = lambda tag, dockerfile, context, *, build_args: (
            built.append((tag, dockerfile, context, build_args)) or
            Image("agent@sha256:" + "d" * 64, "sha256:" + "d" * 64,
                  "sha256:" + "e" * 64, "sha256:" + "f" * 64)
        )
        self.assertEqual(
            "agent@sha256:" + "d" * 64,
            owned_images.resolve_agent(runtime, 501, 20, "base@sha256:" + "a" * 64),
        )
        self.assertEqual(1, len(built))
        self.assertIn("BASE_IMAGE=base@sha256:" + "a" * 64, built[0][3])
        self.assertIn("JJ_IMAGE=" + self.jj_image.reference, built[0][3])

    def test_agent_composition_propagates_engine_errors_without_building(self):
        runtime = type("AgentRuntime", (), {})()
        runtime.provider = "lima-docker"
        runtime.build_platform = lambda: "linux/arm64"
        runtime.upstream_image = lambda reference: reference + "@sha256:" + "e" * 64
        runtime.inspect_image = lambda reference: Image(
            reference, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        )
        runtime.image_if_available = lambda _tag: (_ for _ in ()).throw(OSError("engine unavailable"))
        runtime.build = lambda *_args, **_kwargs: self.fail("engine error became a build")
        with self.assertRaisesRegex(OSError, "engine unavailable"):
            owned_images.resolve_agent(runtime, 501, 20, "base@sha256:" + "a" * 64)

    def test_project_and_installed_helper_resolvers_overlap(self):
        project_started = threading.Event()
        helper_started = threading.Event()

        def project(*_args, **_kwargs):
            project_started.set()
            self.assertTrue(helper_started.wait(1))
            return {"base": Image("base", "base", "base", "base")}

        def helper(*_args, **_kwargs):
            helper_started.set()
            self.assertTrue(project_started.wait(1))
            return {"auth": "helper"}

        runtime = mock.Mock(provider="lima-docker")
        runtime.bake.return_value = {}
        runtime.run_builders.return_value = {}
        policy = {"base": "base", "resolver": {"kind": "bake", "file": "docker-bake.hcl"}}
        auth = [str(owned_images.ROOT / "tools/codex-sandbox/auth-proxy/image")]
        with mock.patch.object(image_resolver, "resolve_policy", side_effect=project), \
                mock.patch("bake.resolve", side_effect=helper):
            prepared = image_resolver.prepare_launch_images(
                runtime, Path.cwd(), {}, include_base=True,
                auth_builder=(auth, Path.cwd()), image_policy=policy,
            )
        self.assertEqual("base", prepared.base)
        self.assertEqual("helper", prepared.auth)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--bounded-fixture':
        bounded_fixture(*sys.argv[2:])
    else:
        unittest.main()
