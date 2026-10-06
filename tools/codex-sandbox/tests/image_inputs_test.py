"""Developer artifacts must not select new runtime images."""

import hashlib
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
    def test_gateway_source_invalidates_the_shared_auth_image(self):
        declaration = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))['declaration']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('auth-proxy/Dockerfile', 'auth-proxy/profile_helper.py',
                         'auth-proxy/codex_profile.py',
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
        self.assertIn('tools/codex-sandbox/auth-proxy/codex_profile.py', paths)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in paths:
                destination = root / source; destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / source, destination)
            with patch.dict(owned['declaration'].__globals__, ROOT=root):
                before = owned['declaration'](['auth'])['target']['auth']['tags']
                (root / 'tools/codex-sandbox/auth-proxy/codex_profile.py').write_text('changed profile')
                self.assertNotEqual(before, owned['declaration'](['auth'])['target']['auth']['tags'])

    def test_agent_packages_runtime_sources_without_tests_or_bytecode(self):
        sources = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))['agent_sources']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / 'tools/codex-sandbox/image/Dockerfile'
            dockerfile.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / dockerfile.relative_to(root), dockerfile)
            runtime = ['tools/codex-sandbox/image/agent-entrypoint',
                       'tools/codex-sandbox/image/agent_supervisor.py',
                       'tools/codex-sandbox/image/codex',
                       'tools/extract-chat/extract-chat',
                       'tools/agent-split/bb', 'tools/agent-split/src/scripts/temp.clj',
                       'libexec/agent-wrappers/jj',
                       'libexec/sandbox-wrappers/docker',
                       'libexec/sandbox-wrappers/gateway-transport',
                       'libexec/sandbox-wrappers/podman']
            noise = ['tools/agent-split/tests/test.clj', 'tools/agent-split/README.md',
                     'libexec/agent-wrappers/__pycache__/jj.pyc',
                     'libexec/sandbox-wrappers/__pycache__/docker.pyc']
            for name in runtime + noise:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            with patch.dict(sources.__globals__, ROOT=root):
                selected = set(map(str, sources()))
            self.assertTrue(set(runtime) <= selected)
            self.assertFalse(set(noise) & selected)

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
            key = lambda: owned['agent_cache_key'](1000, 1000, 'linux/amd64', base, 'a' * 40, root=root)
            for name in ('tools/jj-proxy/route.py', 'config/jj.toml'):
                before = key()
                with (root / name).open('a') as output:
                    output.write('\n# changed authoritative input\n')
                self.assertNotEqual(before, key(), name)

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
