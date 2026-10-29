"""Disposable regressions for admitted-runtime bind checks and mapping identity."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from lima.host import Host
from lima.docker_host import DockerHost
from sandbox_runtime import VMRuntime


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'lima' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mapping_checks = load('guest_mapping_checks', 'check-virtiofs.py')
bind_checks = load('guest_bind_checks', 'check-binds.py')


class GuestMappingTests(unittest.TestCase):
    def test_mapping_checks_both_ids_ownership_and_daemon_cardinality(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = root / '3661'
            process.mkdir()
            mapping = {'host_uid': 1000, 'host_gid': 1000,
                       'guest_uid': 100999, 'guest_gid': 100999}
            for kind in ('uid', 'gid'):
                (process / (kind + '_map')).write_text('0 1000 1\n1 100000 65536\n')
            ownership = SimpleNamespace(st_uid=100999, st_gid=100999)
            with patch.object(mapping_checks.Path, 'lstat', return_value=ownership), \
                    patch.object(mapping_checks.subprocess, 'run', return_value=SimpleNamespace(stdout='3661\n')) as run:
                mapping_checks.check_virtiofs(root / 'scratch', mapping, proc=root)
                run.assert_called_once_with(['pgrep', '-x', 'dockerd'], check=True,
                                            capture_output=True, text=True)
                for field in ('st_uid', 'st_gid'):
                    with self.subTest(owner=field):
                        setattr(ownership, field, 1000)
                        with self.assertRaisesRegex(ValueError, 'UID map is inactive'):
                            mapping_checks.check_virtiofs(root / 'scratch', mapping, proc=root)
                        setattr(ownership, field, 100999)
                for kind in ('uid', 'gid'):
                    path = process / (kind + '_map')
                    for bad in ('0 1000 1\n1 200000 65536\n', '', 'malformed\n'):
                        path.write_text(bad)
                        with self.subTest(kind=kind, bad=bad), self.assertRaises(ValueError):
                            mapping_checks.check_virtiofs(root / 'scratch', mapping, proc=root)
                    path.write_text('0 1000 1\n1 100000 65536\n')
                for pids in ('', '3661\n3662\n', 'not-a-pid\n'):
                    run.return_value.stdout = pids
                    with self.subTest(pids=pids), self.assertRaisesRegex(ValueError, 'exactly one'):
                        mapping_checks.check_virtiofs(root / 'scratch', mapping, proc=root)
                run.side_effect = subprocess.CalledProcessError(1, ['pgrep'])
                with self.assertRaises(subprocess.CalledProcessError):
                    mapping_checks.check_virtiofs(root / 'scratch', mapping, proc=root)

    def test_standalone_helper_fails_closed_on_missing_scratch(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = {'scratch': str(Path(temporary) / 'absent'), 'mapping': {}}
            result = subprocess.run([sys.executable, '-c',
                (ROOT / 'lima/check-virtiofs.py').read_text()],
                input=json.dumps(request), capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('No such file', result.stderr)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux proc maps required')
    def test_serialized_helper_subprocess_checks_mapping_and_preserves_symlink_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / 'scratch'
            scratch.mkdir()
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            pgrep = bin_dir / 'pgrep'
            # The only fake external dependency returns the helper process's
            # own PID. Its real proc maps are safe to inspect and require no VM.
            pgrep.write_text('#!/bin/sh\nset -eu\ntest "$1" = -x\ntest "$2" = dockerd\nprintf "%s\\n" "$PPID"\n')
            pgrep.chmod(0o755)
            mapping = {'guest_uid': os.getuid(), 'guest_gid': os.getgid()}
            for kind in ('uid', 'gid'):
                current = mapping['guest_' + kind]
                pairs = [tuple(map(int, line.split())) for line in
                         Path('/proc/self/' + kind + '_map').read_text().splitlines()]
                start, outer, length = next(pair for pair in pairs
                                            if pair[1] <= current < pair[1] + pair[2])
                mapping['host_' + kind] = start + current - outer
            source = (ROOT / 'lima/check-virtiofs.py').read_text()
            environment = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH']}

            def run(path, expected):
                return subprocess.run([sys.executable, '-c', source],
                    input=json.dumps({'scratch': str(path), 'mapping': expected}),
                    capture_output=True, text=True, env=environment, timeout=10)

            result = run(scratch, mapping)
            self.assertEqual(0, result.returncode, result.stderr)
            for kind in ('uid', 'gid'):
                result = run(scratch, {**mapping, 'host_' + kind: 2 ** 40})
                self.assertNotEqual(0, result.returncode)
                self.assertIn('Docker ' + kind + ' namespace', result.stderr)
                result = run(scratch, {**mapping, 'guest_' + kind: 2 ** 40})
                self.assertNotEqual(0, result.returncode)
                self.assertIn('UID map is inactive', result.stderr)
            # GNU stat without -L examines the link. A dangling target makes
            # accidental Path.stat() dereferencing fail this exact regression.
            link = root / 'scratch-link'
            link.symlink_to(root / 'absent-target')
            result = run(link, mapping)
            self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux proc maps required')
    def test_fake_host_invocation_executes_same_helper_payload(self):
        # Exercise the planned host->guest calling convention before switching
        # live admission: sudo python3 -c SOURCE, JSON stdin, captured errors.
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / 'scratch'
            scratch.mkdir()
            mapping = {'guest_uid': os.getuid(), 'guest_gid': os.getgid()}
            for kind in ('uid', 'gid'):
                current = mapping['guest_' + kind]
                pairs = [tuple(map(int, line.split())) for line in
                         Path('/proc/self/' + kind + '_map').read_text().splitlines()]
                start, outer, length = next(pair for pair in pairs
                                            if pair[1] <= current < pair[1] + pair[2])
                mapping['host_' + kind] = start + current - outer
            source = (ROOT / 'lima/check-virtiofs.py').read_text()

            def guest(_record, *args, **kwargs):
                self.assertEqual(('sudo', 'python3', '-c'), args[:3])
                self.assertEqual(source, args[3])
                with patch.object(sys, 'stdin', io.StringIO(kwargs['input'])), \
                        patch.object(subprocess, 'run', return_value=SimpleNamespace(stdout=str(os.getpid()))):
                    exec(compile(args[3], 'check-virtiofs.py', 'exec'), {'__name__': '__main__'})
                return SimpleNamespace(returncode=0)

            fake_host = SimpleNamespace(state=scratch.parent, guest=Mock(side_effect=guest),
                                        virtiofs_map=Mock(return_value=mapping))
            DockerHost.verify_virtiofs(fake_host, {})
            fake_host.guest.assert_called_once()
            # Guest failures preserve diagnostics and stop admission.
            fake_host.guest.side_effect = subprocess.CalledProcessError(1, ['guest'], stderr='mapping denied\n')
            with patch.object(sys, 'stderr', io.StringIO()) as stderr:
                with self.assertRaises(subprocess.CalledProcessError):
                    DockerHost.verify_virtiofs(fake_host, {})
                self.assertEqual('mapping denied\n', stderr.getvalue())


class AdmittedBindTests(unittest.TestCase):
    def test_docker_defers_access_predictions_but_not_type_or_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / 'config'
            file.write_text('expected')
            binding = {'source': str(file), 'kind': 'file', 'writable': True,
                       'sha256': bind_checks.hashlib.sha256(b'expected').hexdigest()}
            with patch.object(bind_checks.os, 'access', side_effect=AssertionError('predictive access probe')):
                bind_checks.check_binds([{'source': str(root), 'kind': 'directory',
                                         'writable': True}, binding], check_access=False)
                file.write_text('foreign')
                with self.assertRaisesRegex(ValueError, 'differs from the host'):
                    bind_checks.check_binds([binding], check_access=False)
                with self.assertRaisesRegex(ValueError, 'not a directory'):
                    bind_checks.check_binds([{**binding, 'kind': 'directory'}], check_access=False)
            # Actual consumers remain free to raise ordinary permission errors.
            with patch.object(bind_checks.Path, 'open', side_effect=PermissionError('ordinary runtime denial')):
                with self.assertRaises(PermissionError):
                    bind_checks.check_binds([binding], check_access=False)

    def test_docker_guest_argv_defers_access_with_and_without_uid_mapping(self):
        host = object.__new__(DockerHost)
        plain = host.bind_check_argv({'vm_type': 'vz'})
        self.assertEqual('python3', plain[0])
        self.assertEqual('--defer-access', plain[-1])
        mapped = host.bind_check_argv({'vm_type': 'qemu', 'virtiofs_map': {
            'guest_uid': 100999, 'guest_gid': 100999}})
        self.assertEqual(('sudo', 'setpriv', '--reuid=100999', '--regid=100999', '--clear-groups'), mapped[:5])
        self.assertEqual(plain, mapped[5:])
        self.assertNotIn('--defer-access', Host.bind_check_argv(host, {}))
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, *plain[1:]],
                input=json.dumps([{'source': temporary, 'kind': 'directory', 'writable': True}]),
                text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_docker_uses_its_admitted_record_not_new_host_admission(self):
        runtime = object.__new__(Docker)
        runtime.host = Mock()
        runtime.record = {'admitted': 'record'}
        runtime.recovery = False
        sources = [('file', False)]
        runtime.check_binds(sources)
        runtime.host._check_bind_sources.assert_called_once_with(runtime.record, sources)
        runtime.host.verify_runtime.assert_not_called()
        runtime.host.check_binds.assert_not_called()
        runtime.recovery = True
        with self.assertRaisesRegex(Exception, 'recovery permits'):
            runtime.check_binds(sources)
        self.assertEqual(1, runtime.host._check_bind_sources.call_count)

    def test_three_docker_batches_do_not_repeat_constructor_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / 'file'
            file.write_text('host source')
            host = DockerHost(root)
            record = {'phase': 'ready', 'shares': [{'location': str(root), 'writable': True}]}
            with patch('docker_runtime.DockerHost', return_value=host), \
                    patch.object(host, 'record', return_value=record), \
                    patch.object(Docker, 'verify_identity', return_value={
                        'OSType': 'linux', 'Architecture': 'aarch64'}) as identity, \
                    patch.object(host, 'runtime_epoch') as readiness, \
                    patch.object(host, 'verify_virtiofs') as mapping, \
                    patch.object(host, 'guest') as guest:
                runtime = Docker(root)
                for sources in ([(root, True)], [(file, False), (root, False)], [(file, False)]):
                    runtime.check_binds(sources)
                identity.assert_called_once()
                readiness.assert_called_once_with(record)
                mapping.assert_called_once_with(record)
                self.assertEqual(3, guest.call_count)
                # Source/transport failures do not turn into permission to use
                # another engine or silently skip identity checks.
                guest.side_effect = subprocess.CalledProcessError(1, ['guest'])
                with self.assertRaises(subprocess.CalledProcessError):
                    runtime.check_binds([(file, False)])

    def test_strict_mount_runtime_failure_propagates_and_cleans_without_starting(self):
        runtime = object.__new__(Docker)
        runtime.recovery = False
        runtime.client_argv = lambda args: ['disposable-docker', *args]
        runtime.terminate = Mock()
        runtime.popen = Mock()
        creation = Mock()
        creation.wait.return_value = 125
        mount = 'type=bind,src=/owned/source,dst=/work,bind-recursive=disabled'
        with patch('sandbox_runtime.subprocess.Popen', return_value=creation) as spawn:
            with self.assertRaises(subprocess.CalledProcessError) as error:
                with runtime.workload(SimpleNamespace(config='owned-image'), 'owned-container',
                                      ['--mount', mount]):
                    self.fail('a failed mount must not start a workload')
        self.assertEqual(125, error.exception.returncode)
        argv = spawn.call_args.args[0]
        self.assertEqual(mount, argv[argv.index('--mount') + 1])
        self.assertNotIn('-v', argv)
        runtime.popen.assert_not_called()
        runtime.terminate.assert_called_once_with('owned-container')

    def test_native_runtime_keeps_standalone_host_admission(self):
        runtime = object.__new__(VMRuntime)
        runtime.host = Mock()
        runtime.check_binds([('file', False)])
        runtime.host.check_binds.assert_called_once_with([('file', False)])

    def test_admitted_source_checks_keep_share_rw_containment_type_and_file_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = root / 'shared'
            shared.mkdir()
            file = shared / 'file'
            file.write_text('host')
            host = Host(root)
            record = {'phase': 'ready', 'shares': [{'location': str(shared), 'writable': False}]}
            with patch.object(host, 'verify_runtime', side_effect=AssertionError('readmission')), \
                    patch.object(host, 'guest') as guest:
                self.assertEqual([{'source': str(file), 'writable': False}],
                                 host._check_bind_sources(record, [(file, False)]))
                payload = json.loads(guest.call_args.kwargs['input'])
                self.assertEqual('file', payload[0]['kind'])
                self.assertEqual(bind_checks.hashlib.sha256(b'host').hexdigest(), payload[0]['sha256'])
                guest.reset_mock()
                for path, writable in ((file, True), (root, False)):
                    with self.subTest(path=path, writable=writable), self.assertRaisesRegex(ValueError, 'outside'):
                        host._check_bind_sources(record, [(path, writable)])
                guest.assert_not_called()
