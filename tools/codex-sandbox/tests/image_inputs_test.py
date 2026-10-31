"""Developer artifacts must not select new runtime images."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/codex-sandbox'))
from bake import _capture


class ImageInputsTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PI_PACKAGE_DIR'), 'installed Pi SDK required')
    def test_copied_portable_packages_load_with_pi_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / 'home/.pi/agent'
            prefix = '/home/codex/.pi/agent/'
            dockerfile = ROOT / 'tools/codex-sandbox/image/Dockerfile'
            # Consume the actual cache-stage COPY operands, so a missing runtime
            # file fails resource loading even when the checkout has that file.
            for line in dockerfile.read_text().splitlines():
                fields = line.split()
                if not fields or fields[0] != 'COPY' or not fields[-1].startswith(prefix + 'packages/'):
                    continue
                destination = agent / fields[-1].removeprefix(prefix)
                for operand in fields[1:-1]:
                    source = ROOT / operand
                    if source.is_dir():
                        shutil.copytree(source, destination, dirs_exist_ok=True)
                    else:
                        destination.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination / source.name)
            settings = json.loads((ROOT / 'config/pi-agent/settings.json').read_text())
            packages = [entry for entry in settings['packages']
                        if (entry if isinstance(entry, str) else entry['source']).startswith('./packages/')]
            self.assertEqual(3, len(packages))
            (agent / 'settings.json').write_text(json.dumps({'packages': packages}))
            result = subprocess.run(
                ['node', str(ROOT / 'tests/setup/pi_package_resources.mjs'), str(agent), str(root)],
                env={**os.environ, 'HOME': str(root / 'home'), 'PI_CODING_AGENT_DIR': str(agent),
                     'PI_OFFLINE': '1'},
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_gateway_source_invalidates_the_shared_auth_image(self):
        declaration = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))['declaration']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('auth-proxy/Dockerfile', 'auth-proxy/profile_helper.py',
                         'auth-proxy/typed_broker.py', 'gateway.py'):
                path = root / 'tools/codex-sandbox' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            with patch.dict(declaration.__globals__, ROOT=root):
                original = declaration(['auth'])['target']['auth']['tags']
                (root / 'tools/codex-sandbox/gateway.py').write_text('changed listener')
                self.assertNotEqual(original, declaration(['auth'])['target']['auth']['tags'])

    def test_installed_profile_changes_auth_image_identity(self):
        owned = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
        paths = owned['source_paths'](['auth'])['auth']
        self.assertIn('tools/codex-sandbox/auth-proxy/profile_helper.py', paths)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in paths:
                destination = root / source; destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / source, destination)
            with patch.dict(owned['declaration'].__globals__, ROOT=root):
                before = owned['declaration'](['auth'])['target']['auth']['tags']
                (root / 'tools/codex-sandbox/auth-proxy/profile_helper.py').write_text('changed profile')
                self.assertNotEqual(before, owned['declaration'](['auth'])['target']['auth']['tags'])

    def test_agent_packages_runtime_sources_without_tests_or_bytecode(self):
        sources = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))['agent_sources']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / 'tools/codex-sandbox/image/Dockerfile'
            dockerfile.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / dockerfile.relative_to(root), dockerfile)
            runtime = ['tools/codex-sandbox/image/ti',
                       'tools/codex-sandbox/image/agent-entrypoint',
                       'tools/codex-sandbox/image/stage-pi-runtime.mjs',
                       'tools/extract-chat/extract-chat',
                       'tools/pi-codex-subagents/index.ts',
                       'tools/pi-codex-subagents/implementation.ts',
                       'tools/pi-codex-subagents/child-link.ts',
                       'tools/pi-codex-goal/src/index.ts',
                       'tools/pi-codex-goal/prompts/create-goal.md',
                       'tools/pi-session-search/index.ts',
                       'tools/pi-session-search/cli.ts',
                       'libexec/chat-history.clj',
                       'libexec/codex-history.mjs', 'libexec/codex-client.mjs',
                       'bin/codex-to-pi',
                       'tools/agent-split/bb', 'tools/agent-split/src/scripts/temp.clj',
                       'libexec/agent-wrappers/jj',
                       'libexec/sandbox-wrappers/docker',
                       'libexec/sandbox-wrappers/gateway-transport',
                       'libexec/sandbox-wrappers/docker-ssh']
            noise = ['tools/agent-split/tests/test.clj', 'tools/agent-split/README.md',
                     'tools/pi-codex-subagents/index.test.ts',
                     'tools/pi-codex-subagents/node_modules/typebox/index.js',
                     'tools/pi-codex-goal/test/state.test.ts',
                     'tools/pi-session-search/test/cli.test.ts',
                     'libexec/agent-wrappers/__pycache__/jj.pyc',
                     'libexec/sandbox-wrappers/__pycache__/docker.pyc']
            for name in runtime + noise:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            selected = set(map(str, sources(root)))
            self.assertTrue(set(runtime) <= selected)
            self.assertFalse(set(noise) & selected)

    def test_portable_pi_packages_invalidate_image_identity(self):
        owned = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / 'tools/codex-sandbox/image/Dockerfile'
            dockerfile.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / dockerfile.relative_to(root), dockerfile)
            names = ('tools/pi-codex-subagents/core.ts',
                     'tools/pi-codex-goal/src/index.ts',
                     'tools/pi-codex-goal/prompts/create-goal.md',
                     'tools/pi-session-search/index.ts')
            for name in names:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text('original')
            base = SimpleNamespace(content='base', config='config', rootfs='rootfs')
            key = lambda: owned['agent_cache_key'](
                1000, 1000, 'linux/amd64', base, 'a' * 40,
                jj_image='jj@sha256:' + '1' * 64, root=root)
            for name in names:
                before = key()
                (root / name).write_text('changed source')
                self.assertNotEqual(before, key(), name)

    def test_jj_router_and_native_configuration_invalidate_agent_image(self):
        owned = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('tools/codex-sandbox/image/Dockerfile',
                         'tools/jj-proxy/route.py', 'config/jj.toml'):
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(['cp', str(ROOT / name), str(destination)], check=True)
                subprocess.run(['cmp', str(ROOT / name), str(destination)], check=True)
            sources = set(map(str, owned['agent_sources'](root)))
            self.assertIn('tools/jj-proxy/route.py', sources)
            self.assertIn('config/jj.toml', sources)
            base = SimpleNamespace(content='base', config='config', rootfs='rootfs')
            key = lambda: owned['agent_cache_key'](1000, 1000, 'linux/amd64', base, 'a' * 40, jj_image='jj@sha256:' + '1' * 64, root=root)
            for name in ('tools/jj-proxy/route.py', 'config/jj.toml'):
                before = key()
                with (root / name).open('a') as output:
                    output.write('\n# changed authoritative input\n')
                self.assertNotEqual(before, key(), name)

    def test_host_lock_selects_proxy_artifacts_and_cache_identity(self):
        owned = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in owned['source_paths'](['jj'])['jj']:
                destination = root / source
                destination.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(['cp', str(ROOT / source), str(destination)], check=True)
                subprocess.run(['cmp', str(ROOT / source), str(destination)], check=True)
            lock = root / 'config/mise.lock'
            with patch.dict(owned['declaration'].__globals__, ROOT=root):
                for image_platform, architecture, lock_platform in (
                    ('linux/amd64', 'AMD64', 'linux-x64'),
                    ('linux/arm64', 'ARM64', 'linux-arm64'),
                ):
                    with self.subTest(platform=image_platform):
                        targets = []
                        for version, checksum in (('1.2.3', 'a' * 64), ('1.2.4', 'b' * 64)):
                            url = f'https://example.invalid/{version}/{lock_platform}.tar.gz'
                            data = ['[[tools."aqua:jj-vcs/jj"]]', f'version = "{version}"',
                                    f'[tools."aqua:jj-vcs/jj"."platforms.{lock_platform}"]',
                                    f'url = "{url}"', f'checksum = "sha256:{checksum}"']
                            lock.write_text('\n'.join(data) + '\n')
                            target = owned['declaration'](['jj'], platform=image_platform)['target']['jj']
                            self.assertEqual([image_platform], target['platforms'])
                            self.assertEqual({f'JJ_{architecture}_URL': url,
                                              f'JJ_{architecture}_SHA256': checksum}, target['args'])
                            targets.append(target)
                        self.assertNotEqual(targets[0]['tags'], targets[1]['tags'])
                        lock.write_text('\n'.join(data) + '\n[tools."aqua:jj-vcs/jj"."platforms.unused"]\n'
                                        'checksum = "invalid-unused-checksum"\n')
                        self.assertEqual(target['args'], owned['jj_release_args'](image_platform))
                        lock.write_text('\n'.join(data).replace('sha256:' + checksum, 'sha256:bad'))
                        with self.assertRaisesRegex(ValueError, 'SHA-256 checksum'):
                            owned['declaration'](['jj'], platform=image_platform)
                        lock.write_text('\n'.join(data[:2]) + '\n')
                        with self.assertRaisesRegex(ValueError, f'lock JJ for {lock_platform}'):
                            owned['declaration'](['jj'], platform=image_platform)

    def test_zulip_protocol_is_captured_and_changes_image_identity(self):
        owned_images = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root = (temporary / 'repository').resolve()
            for source in owned_images['source_paths'](['zulip'])['zulip']:
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(Path(source).name)

            def capture(name):
                identity = hashlib.sha256()
                destination = temporary / name
                _capture(
                    root, root, destination, identity,
                    owned_images['source_paths'](['zulip'])['zulip'],
                )
                return destination, identity.hexdigest()

            captured, original = capture('first')
            self.assertEqual(
                (captured / 'tools/zulip-proxy/protocol.json').read_text(),
                'protocol.json',
            )
            (root / 'tools/zulip-proxy/protocol.json').write_text('changed protocol')
            _, changed = capture('second')
            self.assertNotEqual(original, changed)

    def test_zulip_key_ignores_developer_files_but_tracks_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builder = root / '.agents/sandbox/zulip-proxy-image'
            builder.parent.mkdir(parents=True)
            shutil.copy2(ROOT / '.agents/sandbox/zulip-proxy-image', builder)
            image = root / 'tools/codex-sandbox/sandbox-image'
            image.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'tools/codex-sandbox/owned_images.py', image.parent / 'owned_images.py')
            shutil.copyfile(Path(__file__).parent / 'fixtures/image-tag.py', image)
            image.chmod(0o755)
            owned = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))
            for source in owned['source_paths'](['zulip'])['zulip']:
                path = root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            def key():
                return subprocess.run([str(builder)], cwd=root, check=True, capture_output=True, text=True).stdout
            first = key()
            noise = root / 'tools/zulip-proxy/__pycache__/server.pyc'
            noise.parent.mkdir()
            noise.write_text('bytecode')
            (noise.parent.parent / 'README.md').write_text('documentation')
            self.assertEqual(first, key())
            (noise.parent.parent / 'server.py').write_text('changed')
            self.assertNotEqual(first, key())


if __name__ == '__main__':
    unittest.main()
