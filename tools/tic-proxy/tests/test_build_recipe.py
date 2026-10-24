"""Owned disposable build/installer fixtures; no host installation or execution.

Synthetic ELF headers exercise artifact validation, not client executability.
Real native/broker execution belongs to the separately selected native tests.
"""
import hashlib
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
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ROOT / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


build = load('build-local')
installer = load('install-bundle')


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
        # Installed artifact directories intentionally deny owner writes. Restore
        # only owned fixture directories before TemporaryDirectory removes them.
        self.addCleanup(self.writable_fixtures)
        self.prefix = self.root / 'home/.local/share/tic-proxy'
        self.prefix.parent.mkdir(parents=True)

    def writable_fixtures(self):
        for directory, subdirs, _ in os.walk(self.root, followlinks=False):
            path = Path(directory)
            if not path.is_symlink():
                path.chmod(0o700)

    def bundle(self, root=None):
        root = root or self.root
        native, broker, client = [root / name for name in ['ti', 'tic-broker', 'ti-proxy']]
        native.write_bytes(b'owned native fixture, not executable machine code')
        broker.write_bytes(b'owned broker fixture, not executable machine code')
        client.write_bytes(elf())
        binding = {'native_revision': installer.PIN, 'policy_version': 1, 'sha256': build.sha256(native)}
        native.with_name('ti.tic-proxy.json').write_text(json.dumps(binding))
        return build.stage_bundle(root, installer.PIN, native, broker, client, 'linux/amd64')

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

    def test_pin_comes_from_the_canonical_build_input(self):
        self.assertEqual((ROOT / 'native-revision').read_text().strip(), installer.PIN)

    def test_guest_artifact_is_static_linux_elf_and_architecture_is_explicit(self):
        path = self.root / 'client'
        for machine, arch in [(62, 'linux/amd64'), (183, 'linux/arm64')]:
            path.write_bytes(elf(machine))
            self.assertEqual(build.guest_platform(path), arch)
        for content in [b'\xcf\xfa\xed\xfe' + b'\0' * 128, elf(interpreter=True), elf(40), elf()[:70]]:
            path.write_bytes(content)
            with self.assertRaises(ValueError):
                build.guest_platform(path)

    def test_installs_content_addressed_artifacts_and_fixed_regular_adapter_manifest(self):
        bundle = self.bundle()
        result = installer.install(bundle, self.prefix)
        self.assertEqual(self.prefix / 'installed.json', result)
        self.assertFalse(result.is_symlink())
        self.assertEqual(1, result.stat().st_nlink)
        installed = json.loads(result.read_bytes())
        destination = self.prefix / bundle.name
        self.assertEqual(str(destination / 'native/ti'), installed['native_executable'])
        self.assertEqual(str(destination / 'host/tic-broker'), installed['broker_executable'])
        self.assertEqual(str(destination / 'guest/ti-proxy'), installed['guest_client_executable'])
        self.assertEqual('linux/amd64', installed['guest_client_platform'])
        self.assertEqual(installer.PIN, installed['native_revision'])
        for relative in ('', *installer.DIRECTORIES):
            self.assertEqual(0o555, stat.S_IMODE((destination / relative).stat().st_mode))
        for relative in installer.FILES:
            path = destination / relative
            self.assertEqual(1, path.stat().st_nlink)
            expected = 0o555 if relative in installer.ARTIFACTS.values() else 0o444
            self.assertEqual(expected, stat.S_IMODE(path.stat().st_mode))
        sandbox = ROOT.parent / 'codex-sandbox'
        with mock.patch.object(sys, 'path', [str(sandbox), *sys.path]):
            from tic_broker import InstalledTicBuild
            binding = InstalledTicBuild.load(result)
        self.assertEqual(installed['native_revision'], binding.native_revision)
        self.assertEqual(Path(installed['guest_client_executable']), binding.guest_client_executable)

    def test_identical_install_verifies_idempotently_without_overwriting(self):
        bundle = self.bundle()
        record = installer.install(bundle, self.prefix)
        paths = [record, *(self.prefix / bundle.name / relative for relative in installer.FILES)]
        before = [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths]
        self.assertEqual(record, installer.install(bundle, self.prefix))
        self.assertEqual(before, [(path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths])

    def test_existing_mismatch_is_never_repaired_or_overwritten(self):
        for changed in ('record', 'artifact', 'binding', 'directory-mode', 'file-mode', 'hardlink', 'extra'):
            with self.subTest(changed=changed):
                case = self.root / changed
                case.mkdir()
                bundle = self.bundle(case)
                prefix = case / 'installed'
                record = installer.install(bundle, prefix)
                destination = prefix / bundle.name
                mutated = record
                if changed in ('record', 'artifact', 'binding', 'file-mode'):
                    mutated = {'record': record, 'artifact': destination / 'host/tic-broker',
                               'binding': destination / 'native/ti.tic-proxy.json',
                               'file-mode': destination / 'guest/ti-proxy'}[changed]
                    mutated.chmod(0o600)
                    if changed != 'file-mode':
                        mutated.write_bytes(b'fixture mismatch')
                elif changed == 'directory-mode':
                    mutated = destination / 'host'
                    mutated.chmod(0o755)
                elif changed == 'hardlink':
                    mutated = destination / 'host/tic-broker'
                    os.link(mutated, case / 'artifact-alias')
                else:
                    destination.chmod(0o755)
                    mutated = destination / 'extra'
                    mutated.write_text('unexpected')
                before = mutated.lstat()
                contents = mutated.read_bytes() if mutated.is_file() else None
                with self.assertRaises(ValueError):
                    installer.install(bundle, prefix)
                self.assertEqual(before.st_ino, mutated.lstat().st_ino)
                self.assertEqual(before.st_mode, mutated.lstat().st_mode)
                if contents is not None:
                    self.assertEqual(contents, mutated.read_bytes())

    def test_a_different_build_does_not_replace_the_stable_installed_manifest(self):
        bundle = self.bundle()
        record = installer.install(bundle, self.prefix)
        before = record.read_bytes()
        source = self.root / 'next-build'
        source.mkdir()
        next_bundle = self.bundle(source)
        native = next_bundle / 'native/ti'
        native.chmod(0o600)
        native.write_bytes(b'different owned native artifact')
        next_bundle = self.rewrite_manifest(next_bundle, lambda value: value['native'].update(sha256=build.sha256(native)))
        binding = next_bundle / 'native/ti.tic-proxy.json'
        binding.chmod(0o600)
        binding.write_text(json.dumps({'native_revision': installer.PIN, 'policy_version': 1,
                                       'sha256': build.sha256(next_bundle / 'native/ti')}))
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            installer.install(next_bundle, self.prefix)
        self.assertEqual(before, record.read_bytes())
        self.assertFalse((self.prefix / next_bundle.name).exists())

    def test_corrupt_escaping_or_ambiguous_bundle_is_not_installed(self):
        for changed in ('bytes', 'name', 'path', 'binding', 'leaf-symlink', 'directory-symlink', 'extra',
                        'boolean-version', 'wrong-pin', 'duplicate', 'platform', 'dynamic-client'):
            with self.subTest(changed=changed):
                case = self.root / changed
                case.mkdir()
                bundle = self.bundle(case)
                if changed == 'bytes':
                    path = bundle / 'host/tic-broker'
                    path.chmod(0o600)
                    path.write_bytes(b'changed')
                elif changed == 'name':
                    destination = bundle.with_name('bundle-' + '0' * 64)
                    bundle.rename(destination)
                    bundle = destination
                elif changed == 'path':
                    bundle = self.rewrite_manifest(bundle, lambda value: value['client'].update(path='../outside'))
                elif changed == 'binding':
                    path = bundle / 'native/ti.tic-proxy.json'
                    path.chmod(0o600)
                    path.write_text('{}')
                elif changed == 'leaf-symlink':
                    path = bundle / 'host/tic-broker'
                    path.unlink()
                    path.symlink_to(case / 'tic-broker')  # Same bytes/hash; still forbidden.
                elif changed == 'directory-symlink':
                    path = bundle / 'host'
                    outside = case / 'directory-alias-target'
                    path.rename(outside)
                    path.symlink_to(outside, target_is_directory=True)
                elif changed == 'extra':
                    (bundle / 'unexpected').write_text('extra')
                elif changed == 'boolean-version':
                    bundle = self.rewrite_manifest(bundle, lambda value: value.update(version=True))
                elif changed == 'wrong-pin':
                    bundle = self.rewrite_manifest(bundle, lambda value: value.update(native_revision='0' * 40))
                elif changed == 'duplicate':
                    path = bundle / 'manifest.json'
                    path.chmod(0o600)
                    path.write_text('{"version":1,"version":1}')
                elif changed == 'platform':
                    bundle = self.rewrite_manifest(bundle, lambda value: value['client'].update(platform='linux/arm64'))
                else:
                    path = bundle / 'guest/ti-proxy'
                    path.chmod(0o600)
                    path.write_bytes(elf(interpreter=True))
                    bundle = self.rewrite_manifest(bundle, lambda value: value['client'].update(sha256=build.sha256(path)))
                prefix = case / 'must-not-exist'
                with self.assertRaises(ValueError):
                    installer.install(bundle, prefix)
                self.assertFalse(prefix.exists())

    def test_known_guest_mount_overlap_is_rejected_in_both_directions(self):
        bundle = self.bundle()
        for mount in (self.prefix.parent, self.prefix / 'future-guest-write'):
            mount.mkdir(parents=True, exist_ok=True)
            with self.assertRaisesRegex(ValueError, 'guest-writable'):
                installer.install(bundle, self.prefix, [mount])
        self.assertFalse((self.prefix / 'installed.json').exists())

    def test_unsafe_parent_and_symlinked_prefix_are_rejected(self):
        bundle = self.bundle()
        unsafe = self.root / 'unsafe'
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        with self.assertRaises(ValueError):
            installer.install(bundle, unsafe / 'installation')
        self.assertFalse((unsafe / 'installation').exists())
        alias = self.root / 'alias'
        alias.symlink_to(self.prefix.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            installer.install(bundle, alias / 'installation')

    def test_existing_partial_destination_is_not_taken_over(self):
        bundle = self.bundle()
        destination = self.prefix / bundle.name
        destination.mkdir(parents=True)
        before = destination.stat().st_ino
        with self.assertRaises(ValueError):
            installer.install(bundle, self.prefix)
        self.assertEqual(before, destination.stat().st_ino)
        self.assertEqual([], list(destination.iterdir()))
        self.assertFalse((self.prefix / 'installed.json').exists())

    def test_changed_copy_or_native_binding_leaves_no_stage_or_record(self):
        bundle = self.bundle()
        copy = shutil.copyfile
        for changed in ('artifact', 'binding'):
            with self.subTest(changed=changed):
                prefix = self.root / ('failed-' + changed)

                def corrupt(source, destination):
                    result = copy(source, destination)
                    if (changed == 'artifact' and Path(destination).name == 'tic-broker'
                            or changed == 'binding' and Path(destination).name == 'ti.tic-proxy.json'):
                        Path(destination).write_bytes(b'changed during copy')
                    return result

                with mock.patch.object(installer.shutil, 'copyfile', side_effect=corrupt):
                    with self.assertRaises(ValueError):
                        installer.install(bundle, prefix)
                self.assertFalse(prefix.exists())
                self.assertFalse(any(path.name.startswith('.tic-install-') for path in self.root.iterdir()))

    def test_cli_only_installs_into_explicit_owned_fixture_prefix(self):
        bundle = self.bundle()
        result = subprocess.run([sys.executable, str(ROOT / 'install-bundle'), str(bundle),
                                 '--prefix', str(self.prefix), '--guest-writable-root', str(self.root / 'workspace')],
                                capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)  # Exclusions must resolve; no guessed authority.
        (self.root / 'workspace').mkdir()
        result = subprocess.run([sys.executable, str(ROOT / 'install-bundle'), str(bundle),
                                 '--prefix', str(self.prefix), '--guest-writable-root', str(self.root / 'workspace')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(str(self.prefix / 'installed.json'), result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
