"""Disposable bundle/cache fixtures; never install in user HOME or start providers."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tarfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'codex-sandbox'))
import bundle as bundles
import tic_artifact
from tic_broker import InstalledTicBuild

loader = importlib.machinery.SourceFileLoader('tic_build_local', str(ROOT / 'build-local'))
spec = importlib.util.spec_from_loader(loader.name, loader)
build = importlib.util.module_from_spec(spec)
loader.exec_module(build)


def elf(machine=62, interpreter=False):
    header = bytearray(64)
    header[:8] = b'\x7fELF\x02\x01\x01\x00'
    header[18:20] = machine.to_bytes(2, 'little')
    header[32:40] = (64).to_bytes(8, 'little')
    header[54:56] = (56).to_bytes(2, 'little')
    header[56:58] = (1).to_bytes(2, 'little')
    program = bytearray(56)
    program[:4] = (3 if interpreter else 1).to_bytes(4, 'little')
    return header + program


class BuildRecipeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.addCleanup(self.writable_fixtures)
        self.prefix = self.root / 'cache'

    def writable_fixtures(self):
        for directory, _, _ in os.walk(self.root, followlinks=False):
            if not Path(directory).is_symlink():
                Path(directory).chmod(0o700)

    def bundle(self, root=None, identity=None):
        root = root or self.root
        native, broker, client = [root / name for name in ['ti', 'tic-broker', 'ti-proxy']]
        native.write_bytes(b'owned native fixture, not executable machine code')
        broker.write_bytes(b'owned broker fixture, not executable machine code')
        client.write_bytes(elf())
        binding = dict(native_revision=bundles.PIN, policy_version=1, sha256=build.sha256(native))
        native.with_name('ti.tic-proxy.json').write_text(json.dumps(binding))
        return build.stage_bundle(root, bundles.PIN, native, broker, client, 'linux/amd64', identity)

    def rewrite_manifest(self, bundle, modify):
        path = bundle / 'manifest.json'
        value = json.loads(path.read_bytes())
        modify(value)
        path.chmod(0o600)
        encoded = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
        path.write_bytes(encoded)
        destination = bundle.with_name('bundle-' + hashlib.sha256(encoded).hexdigest())
        bundle.rename(destination)
        return destination

    def resolve(self, provision, **kwargs):
        return tic_artifact.resolve_bundle(self.prefix, 'linux/amd64', (), provision, **kwargs)

    def test_static_linux_elf_and_architecture(self):
        path = self.root / 'client'
        for machine, arch in [(62, 'linux/amd64'), (183, 'linux/arm64')]:
            path.write_bytes(elf(machine))
            self.assertEqual(build.guest_platform(path), arch)
        for content in [b'\xcf\xfa\xed\xfe' + b'\0' * 128, elf(interpreter=True), elf(40), elf()[:70]]:
            path.write_bytes(content)
            with self.assertRaises(ValueError):
                build.guest_platform(path)

    def test_cache_uses_one_relative_manifest_without_installed_record(self):
        source = self.bundle()
        provision = mock.Mock(return_value=source)
        manifest = self.resolve(provision)
        provision.assert_called_once_with(bundles.build_identity(bundles.host_platform(), 'linux/amd64'))
        self.assertEqual([], list(self.root.rglob('installed.json')))
        self.assertEqual(1, len(list(manifest.parent.glob('*.json'))))
        value = InstalledTicBuild.load(manifest)
        self.assertEqual(manifest.parent / 'native/ti', value.native_executable)
        self.assertNotEqual(source / 'native/ti', value.native_executable)
        self.assertEqual(bundles.PIN, value.native_revision)
        for relative in ('', *bundles.DIRECTORIES):
            self.assertEqual(0o555, stat.S_IMODE((manifest.parent / relative).stat().st_mode))
        for relative in bundles.FILES:
            path = manifest.parent / relative
            self.assertEqual(1, path.stat().st_nlink)
            self.assertEqual(0o555 if relative in bundles.ARTIFACTS.values() else 0o444,
                             stat.S_IMODE(path.stat().st_mode))

    def test_warm_cache_never_requires_source_or_rewrites_artifacts(self):
        manifest = self.resolve(mock.Mock(return_value=self.bundle()))
        before = [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
                  for p in manifest.parent.rglob('*') if p.is_file()]
        no_build = mock.Mock(side_effect=AssertionError('warm cache must not provision'))
        self.assertEqual(manifest, self.resolve(no_build))
        self.assertEqual(before, [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
                                  for p in manifest.parent.rglob('*') if p.is_file()])

    def test_warm_cache_and_loaded_build_never_hash_artifact_contents(self):
        manifest = self.resolve(mock.Mock(return_value=self.bundle()))
        with mock.patch.object(hashlib, 'file_digest', side_effect=AssertionError('runtime file hashing')):
            self.assertEqual(manifest, self.resolve(mock.Mock(side_effect=AssertionError('must stay warm'))))
            InstalledTicBuild.load(manifest).verify()

    def test_warm_cache_rejects_symlinked_artifacts_and_directories_without_hashing(self):
        for relative in ('host/tic-broker', 'native'):
            with self.subTest(relative=relative):
                case = self.root / relative.replace('/', '-')
                case.mkdir()
                self.prefix = case / 'cache'
                manifest = self.resolve(mock.Mock(return_value=self.bundle(case)))
                original = manifest.parent / relative
                alias = case / 'outside-alias'
                original.parent.chmod(0o755)
                if original.is_dir():
                    original.chmod(0o755)
                original.rename(alias)
                original.symlink_to(alias, target_is_directory=alias.is_dir())
                original.parent.chmod(0o555)
                with mock.patch.object(hashlib, 'file_digest', side_effect=AssertionError('runtime file hashing')):
                    with self.assertRaisesRegex(ValueError, 'symlink'):
                        self.resolve(mock.Mock(side_effect=AssertionError('must not repair')))

    def test_warm_cache_rejects_wrong_owner_without_hashing(self):
        self.resolve(mock.Mock(return_value=self.bundle()))
        wrong_owner = os.getuid() + 1
        with mock.patch.object(os, 'getuid', return_value=wrong_owner), mock.patch.object(
                hashlib, 'file_digest', side_effect=AssertionError('runtime file hashing')):
            with self.assertRaisesRegex(ValueError, 'ownership'):
                self.resolve(mock.Mock(side_effect=AssertionError('must not repair')))

    def test_incoming_artifact_bytes_are_verified_before_publication(self):
        source = self.bundle()
        artifact = source / 'host/tic-broker'
        artifact.chmod(0o755)
        artifact.write_bytes(b'changed after build manifest')
        artifact.chmod(0o555)
        with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
            self.resolve(mock.Mock(return_value=source))
        self.assertEqual(['.resolve.lock'], [p.name for p in self.prefix.iterdir()])

    def test_host_rewriting_protected_bytes_is_not_a_warm_integrity_contract(self):
        manifest = self.resolve(mock.Mock(return_value=self.bundle()))
        artifact = manifest.parent / 'host/tic-broker'
        artifact.chmod(0o755)
        artifact.write_bytes(b'host manually rewrote its own immutable snapshot')
        artifact.chmod(0o555)
        # This is not guest authority: the cache is outside writable mounts.
        with mock.patch.object(hashlib, 'file_digest', side_effect=AssertionError('runtime file hashing')):
            self.assertEqual(manifest, self.resolve(mock.Mock(side_effect=AssertionError('must stay warm'))))
            InstalledTicBuild.load(manifest).verify()

    def test_development_bundle_uses_same_copy_and_validation(self):
        source = self.bundle()
        manifest = self.resolve(mock.Mock(side_effect=AssertionError('override must not build')), local_bundle=source)
        self.assertEqual((source / 'manifest.json').read_bytes(), manifest.read_bytes())
        self.assertEqual(manifest, self.resolve(mock.Mock(), local_bundle=source))

    def test_proxy_source_changes_cannot_reuse_old_bundle(self):
        source = self.bundle()
        self.resolve(mock.Mock(return_value=source))
        original = bundles.build_identity(bundles.host_platform(), 'linux/amd64')
        changed = {**original, 'proxy_source': '0' * 64}
        provision = mock.Mock(return_value=source)
        with mock.patch.object(tic_artifact, 'build_identity', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'current proxy sources'):
                self.resolve(provision)
        provision.assert_called_once_with(changed)
        self.assertEqual(1, len([p for p in self.prefix.iterdir() if p.name != '.resolve.lock']))

    def test_identity_hashes_source_bytes_and_paths_not_mtime_or_checkout(self):
        copied = self.root / 'proxy-source'
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns('target', 'tests', '__pycache__'))
        original = bundles.source_identity(copied)
        source = copied / 'src/protocol.rs'
        os.utime(source, (1, 1))
        self.assertEqual(original, bundles.source_identity(copied))
        source.write_bytes(source.read_bytes() + b'\n// owned test change\n')
        self.assertNotEqual(original, bundles.source_identity(copied))

    def test_old_wire_bundle_and_wrong_native_policy_platform_source_are_rejected(self):
        changes = [lambda v: v.update(version=1), lambda v: v.update(native_revision='0' * 40),
                   lambda v: v.update(policy_version=2), lambda v: v['build'].update(wire_version=1),
                   lambda v: v['build'].update(host_platform='darwin/arm64'),
                   lambda v: v['build'].update(proxy_source='0' * 64),
                   lambda v: v['build'].update(guest_platform='linux/arm64'),
                   lambda v: v['native'].update(path='/outside/ti'), lambda v: v.update(extra=True)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                case = self.root / str(index)
                case.mkdir()
                source = self.rewrite_manifest(self.bundle(case), change)
                with self.assertRaises((ValueError, TypeError)):
                    self.resolve(mock.Mock(return_value=source))
                self.assertEqual([], [p for p in self.prefix.iterdir() if p.name != '.resolve.lock'] if self.prefix.exists() else [])

    def test_partial_cache_and_unsafe_protection_fail_without_repair_or_rebuild(self):
        for changed in ('manifest', 'binding', 'directory-mode', 'file-mode', 'hardlink', 'extra', 'missing'):
            with self.subTest(changed=changed):
                case = self.root / changed
                case.mkdir()
                self.prefix = case / 'cache'
                manifest = self.resolve(mock.Mock(return_value=self.bundle(case)))
                destination = manifest.parent
                mutated = {'manifest': manifest,
                           'binding': destination / 'native/ti.tic-proxy.json',
                           'file-mode': destination / 'guest/ti-proxy'}.get(changed, destination)
                if changed in ('manifest', 'binding', 'file-mode'):
                    mutated.chmod(0o600)
                    if changed != 'file-mode':
                        mutated.write_bytes(b'fixture tamper')
                elif changed == 'directory-mode':
                    mutated.chmod(0o755)
                elif changed == 'hardlink':
                    os.link(destination / 'host/tic-broker', case / 'alias')
                elif changed == 'extra':
                    mutated.chmod(0o755)
                    (mutated / 'extra').write_text('unexpected')
                else:
                    mutated.chmod(0o755)
                    manifest.unlink()
                before = mutated.lstat()
                provision = mock.Mock(side_effect=AssertionError('must not repair'))
                with self.assertRaises((ValueError, OSError)):
                    self.resolve(provision)
                provision.assert_not_called()
                self.assertEqual(before, mutated.lstat())

    def test_empty_authored_key_is_not_adopted(self):
        source = self.bundle()
        manifest = self.resolve(mock.Mock(return_value=source))
        bundles.remove_stage(manifest.parent)
        with self.assertRaisesRegex(ValueError, 'partial or ambiguous'):
            self.resolve(mock.Mock(side_effect=AssertionError('must not repair')))

    def test_cache_outside_canonical_writable_roots_including_symlink_aliases(self):
        source = self.bundle()
        alias = self.root / 'writable-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        provision = mock.Mock(return_value=source)
        with self.assertRaisesRegex(ValueError, 'guest-writable'):
            tic_artifact.resolve_bundle(self.prefix, 'linux/amd64', [alias], provision)
        provision.assert_not_called()
        cache_alias = self.root / 'cache-alias'
        cache_alias.symlink_to(self.prefix, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            tic_artifact.resolve_bundle(cache_alias, 'linux/amd64', [], provision)

    def test_symlinked_bundle_ancestors_and_hardlinked_cache_files_are_rejected(self):
        source = self.bundle()
        native = source / 'native'
        native.rename(self.root / 'native-alias')
        native.symlink_to(self.root / 'native-alias', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.resolve(mock.Mock(return_value=source))
        self.assertEqual([], [p for p in self.prefix.iterdir() if p.name != '.resolve.lock'] if self.prefix.exists() else [])

    def test_host_native_source_setting_is_one_path_not_an_artifact_record(self):
        home = self.root / 'home'
        setting = home / '.config/codex-sandbox/tic-native-source'
        setting.parent.mkdir(parents=True)
        source = self.root / 'native repo with spaces'
        source.mkdir()
        setting.write_text(str(source) + '\n')
        setting.chmod(0o600)
        self.assertEqual(source, tic_artifact.native_source(home, ()))
        for content in ('relative/path', str(source) + '\nsecond line', 'bad\0path', 'x' * 4097):
            setting.write_text(content)
            with self.assertRaises(ValueError):
                tic_artifact.native_source(home, ())
        setting.write_text(str(source))
        setting.chmod(0o644)
        with self.assertRaisesRegex(ValueError, '0600'):
            tic_artifact.native_source(home, ())
        setting.chmod(0o600)
        os.link(setting, self.root / 'setting-alias')
        with self.assertRaisesRegex(ValueError, 'single-link'):
            tic_artifact.native_source(home, ())
        (self.root / 'setting-alias').unlink()
        with self.assertRaisesRegex(ValueError, 'guest-writable'):
            tic_artifact.native_source(home, [home])
        setting.unlink()
        setting.symlink_to(self.root / 'ti')
        (self.root / 'ti').write_text(str(source))
        with self.assertRaisesRegex(ValueError, 'canonical'):
            tic_artifact.native_source(home, ())

    def test_source_configuration_validates_pin_and_is_idempotent_without_overwrite(self):
        home, repository, other = [self.root / name for name in ('home', 'native-repository', 'other')]
        repository.mkdir()
        other.mkdir()
        success = mock.Mock(stdout=bundles.PIN + '\n')
        with mock.patch.object(tic_artifact.subprocess, 'run', return_value=success) as git:
            setting = tic_artifact.configure_native_source(home, repository)
            self.assertEqual(['git', '-C', str(repository), 'rev-parse', bundles.PIN + '^{commit}'],
                             git.call_args.args[0])
            self.assertEqual(repository, tic_artifact.native_source(home, ()))
            self.assertEqual(0o600, stat.S_IMODE(setting.stat().st_mode))
            before = (setting.stat().st_ino, setting.stat().st_mtime_ns, setting.read_bytes())
            self.assertEqual(setting, tic_artifact.configure_native_source(home, repository))
            self.assertEqual(before, (setting.stat().st_ino, setting.stat().st_mtime_ns, setting.read_bytes()))
            with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
                tic_artifact.configure_native_source(home, other)
            self.assertEqual(before, (setting.stat().st_ino, setting.stat().st_mtime_ns, setting.read_bytes()))
            setting.write_text('authored malformed setting')
            before = setting.read_bytes()
            with self.assertRaises(ValueError):
                tic_artifact.configure_native_source(home, repository)
            self.assertEqual(before, setting.read_bytes())
        self.assertEqual([], list(setting.parent.glob('.tic-native-source-*')))

    def test_explicit_source_update_is_atomic_and_preserves_unrelated_host_configuration(self):
        home, repository, other = [self.root / name for name in ('home', 'native-repository', 'other')]
        repository.mkdir()
        other.mkdir()
        with mock.patch.object(tic_artifact.subprocess, 'run', return_value=mock.Mock(stdout=bundles.PIN)):
            setting = tic_artifact.configure_native_source(home, repository)
            unrelated = setting.with_name('github-token')
            unrelated.write_bytes(b'owned unrelated fixture')
            before = unrelated.stat(), unrelated.read_bytes()
            repository.rmdir()  # Explicit updates can replace a stale source location.
            self.assertEqual(setting, tic_artifact.configure_native_source(home, other, replace=True))
            self.assertEqual(other, tic_artifact.native_source(home, ()))
            self.assertEqual(0o600, stat.S_IMODE(setting.stat().st_mode))
            self.assertEqual(before, (unrelated.stat(), unrelated.read_bytes()))
            self.assertEqual([], list(setting.parent.glob('.tic-native-source-*')))
            setting.chmod(0o644)
            before = setting.read_bytes()
            with self.assertRaisesRegex(ValueError, '0600'):
                tic_artifact.configure_native_source(home, other, replace=True)
            self.assertEqual(before, setting.read_bytes())

    def test_failed_explicit_source_update_keeps_previous_setting_and_removes_private_stage(self):
        home, repository, other = [self.root / name for name in ('home', 'native-repository', 'other')]
        repository.mkdir()
        other.mkdir()
        with mock.patch.object(tic_artifact.subprocess, 'run', return_value=mock.Mock(stdout=bundles.PIN)):
            setting = tic_artifact.configure_native_source(home, repository)
            before = setting.stat(), setting.read_bytes()
            with mock.patch.object(tic_artifact.os, 'replace', side_effect=OSError('owned publish failure')):
                with self.assertRaisesRegex(OSError, 'owned publish failure'):
                    tic_artifact.configure_native_source(home, other, replace=True)
            self.assertEqual(before, (setting.stat(), setting.read_bytes()))
            self.assertEqual([], list(setting.parent.glob('.tic-native-source-*')))

    def test_source_configuration_failed_git_or_wrong_pin_never_publishes_setting(self):
        repository = self.root / 'native-repository'
        repository.mkdir()
        for index, result in enumerate((mock.Mock(stdout='0' * 40), subprocess.CalledProcessError(1, 'git'))):
            home = self.root / str(index)
            if isinstance(result, Exception):
                operation = mock.patch.object(tic_artifact.subprocess, 'run', side_effect=result)
            else:
                operation = mock.patch.object(tic_artifact.subprocess, 'run', return_value=result)
            with operation, self.assertRaises((ValueError, subprocess.CalledProcessError)):
                tic_artifact.configure_native_source(home, repository)
            self.assertFalse(home.exists())

    def test_normal_builder_uses_guest_target_flag_and_requires_one_valid_bundle(self):
        source = self.bundle()
        expected = bundles.build_identity(bundles.host_platform(), 'linux/amd64')
        native = self.root / 'native-repository'
        completed = mock.Mock(stdout='native executable: ignored\nstaged bundle: ' + str(source) + '\n')
        with mock.patch.object(tic_artifact.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(source, tic_artifact.build_bundle(native, expected))
        self.assertEqual([sys.executable, str(ROOT / 'build-local'), '--guest-platform', 'linux/amd64',
                          str(native), 'build', '--bins'], run.call_args.args[0])
        self.assertTrue(run.call_args.kwargs['check'])
        for output in ('', 'staged bundle: one\nstaged bundle: two\n'):
            with mock.patch.object(tic_artifact.subprocess, 'run', return_value=mock.Mock(stdout=output)):
                with self.assertRaisesRegex(ValueError, 'one staged bundle'):
                    tic_artifact.build_bundle(native, expected)

    def test_concurrent_normal_resolvers_publish_one_whole_key_and_provision_once(self):
        source = self.bundle()
        provision = mock.Mock(return_value=source)
        copying, release, contending = threading.Event(), threading.Event(), threading.Event()
        original_copy, original_flock = bundles.shutil.copyfile, tic_artifact.fcntl.flock
        def copy(src, dst):
            if Path(dst).name == 'tic-broker' and not copying.is_set():
                copying.set()
                self.assertTrue(release.wait(5))
            return original_copy(src, dst)
        def flock(fd, mode):
            if copying.is_set() and not release.is_set():
                contending.set()
            return original_flock(fd, mode)
        with mock.patch.object(bundles.shutil, 'copyfile', side_effect=copy), mock.patch.object(
                tic_artifact.fcntl, 'flock', side_effect=flock), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.resolve, provision)
            try:
                self.assertTrue(copying.wait(5))
                self.assertEqual([], [p for p in self.prefix.iterdir() if not p.name.startswith('.')])
                second = pool.submit(self.resolve, provision)
                self.assertTrue(contending.wait(5))
                self.assertFalse(second.done())
            finally:
                release.set()
            one, two = first.result(timeout=5), second.result(timeout=5)
        self.assertEqual(one, two)
        provision.assert_called_once()
        self.assertEqual(1, len([p for p in self.prefix.iterdir() if not p.name.startswith('.')]))
        _, manifest, binding = bundles.validate_bundle(one.parent)
        bundles.verify_copy(one.parent, one.read_bytes(), manifest, binding)
        self.assertEqual([], list(self.prefix.glob('.tic-key-*')))

    def test_build_local_serializes_native_outputs_through_bundle_staging(self):
        root = self.root / 'builder/tools/tic-proxy'
        root.mkdir(parents=True)
        (root / 'native-revision').write_text(bundles.PIN)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w'):
            pass
        first_native, release, second_waiting = threading.Event(), threading.Event(), threading.Event()
        original_flock, original_stage = build.fcntl.flock, build.stage_bundle
        results = []
        def flock(fd, mode):
            if first_native.is_set() and not release.is_set():
                second_waiting.set()
            return original_flock(fd, mode)
        def cargo(argv, *, env, check):
            # Every native/proxy build uses the same lean dev profile, even if
            # the caller's environment requested bulky debug information.
            self.assertEqual('0', env['CARGO_PROFILE_DEV_DEBUG'])
            output = Path(env['CARGO_TARGET_DIR']) / 'debug'
            output.mkdir(parents=True, exist_ok=True)
            name = threading.current_thread().name.encode()
            if '-p' in argv:
                (output / 'ti').write_bytes(name)
                if not first_native.is_set():
                    first_native.set()
                    self.assertTrue(release.wait(5))
            else:
                (output / 'tic-broker').write_bytes(name)
                (output / 'ti-proxy').write_bytes(elf())
        def stage(*args):
            path = original_stage(*args)
            self.assertEqual((path / 'native/ti').read_bytes(), (path / 'host/tic-broker').read_bytes())
            results.append(path)
            return path
        identity = bundles.build_identity(bundles.host_platform(), 'linux/amd64')
        with mock.patch.dict(os.environ, {'CARGO_PROFILE_DEV_DEBUG': '2'}), mock.patch.object(
                build, '__file__', str(root / 'build-local')), mock.patch.object(
                build.sys, 'argv', ['build-local', str(self.root), 'build', '--bins']), mock.patch.object(
                build, 'build_identity', return_value=identity), mock.patch.object(
                build.subprocess, 'check_output', side_effect=lambda argv, **kw: bundles.PIN if 'rev-parse' in argv else archive.getvalue()), mock.patch.object(
                build.subprocess, 'run', side_effect=cargo), mock.patch.object(build.fcntl, 'flock', side_effect=flock), mock.patch.object(
                build, 'stage_bundle', side_effect=stage), mock.patch('builtins.print'), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(build.main)
            try:
                self.assertTrue(first_native.wait(5))
                second = pool.submit(build.main)
                self.assertTrue(second_waiting.wait(5))
                self.assertFalse(second.done())
            finally:
                release.set()
            first.result(timeout=5)
            second.result(timeout=5)
        self.assertEqual(2, len(results))
        self.assertNotEqual(results[0], results[1])

    def test_optional_cli_uses_the_same_source_key_without_a_global_record(self):
        source = self.bundle()
        completed = subprocess.run([sys.executable, str(ROOT / 'install-bundle'), str(source),
                                    '--prefix', str(self.prefix)], check=True, capture_output=True, text=True)
        manifest = Path(completed.stdout.strip())
        self.assertEqual(manifest, self.resolve(mock.Mock(side_effect=AssertionError('must reuse'))))
        self.assertEqual([], list(self.prefix.rglob('installed.json')))

    def test_copy_failure_or_changed_source_publishes_no_partial_key(self):
        source = self.bundle()
        original = bundles.shutil.copyfile
        for failure in ('copy', 'binding'):
            with self.subTest(failure=failure):
                self.prefix = self.root / ('cache-' + failure)
                def copy(src, dst):
                    result = original(src, dst)
                    if (failure == 'copy' and Path(dst).name == 'tic-broker'
                            or failure == 'binding' and Path(dst).name == 'ti.tic-proxy.json'):
                        Path(dst).write_bytes(b'changed during copy')
                    return result
                with mock.patch.object(bundles.shutil, 'copyfile', side_effect=copy):
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        self.resolve(mock.Mock(return_value=source))
                self.assertEqual(['.resolve.lock'], [p.name for p in self.prefix.iterdir()])

    def test_duplicate_manifest_fields_and_oversize_are_rejected(self):
        for index, content in enumerate((b'{"version":2,"version":2}', b' ' * 65537)):
            with self.subTest(index=index):
                case = self.root / str(index)
                case.mkdir()
                source = self.bundle(case)
                manifest = source / 'manifest.json'
                manifest.chmod(0o600)
                manifest.write_bytes(content)
                with self.assertRaises(ValueError):
                    self.resolve(mock.Mock(return_value=source))
                self.assertEqual([], [p for p in self.prefix.iterdir() if p.name != '.resolve.lock'] if self.prefix.exists() else [])

    def test_build_failure_publishes_no_cache(self):
        with self.assertRaisesRegex(ValueError, 'owned failure'):
            self.resolve(mock.Mock(side_effect=ValueError('owned failure')))
        self.assertEqual([], [p for p in self.prefix.iterdir() if p.name != '.resolve.lock'] if self.prefix.exists() else [])


if __name__ == '__main__':
    unittest.main()
