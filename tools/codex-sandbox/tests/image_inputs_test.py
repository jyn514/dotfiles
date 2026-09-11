"""Developer artifacts must not select new runtime images."""

from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class ImageInputsTest(unittest.TestCase):
    def test_gateway_source_invalidates_the_shared_auth_image(self):
        declaration = runpy.run_path(str(ROOT / 'tools/codex-sandbox/owned_images.py'))['declaration']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('auth-proxy/Dockerfile', 'auth-proxy/server.py', 'gateway.py'):
                path = root / 'tools/codex-sandbox' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            with patch.dict(declaration.__globals__, ROOT=root):
                original = declaration(['auth'])['target']['auth']['tags']
                (root / 'tools/codex-sandbox/gateway.py').write_text('changed listener')
                self.assertNotEqual(original, declaration(['auth'])['target']['auth']['tags'])

    def test_agent_packages_runtime_sources_without_tests_or_bytecode(self):
        sources = runpy.run_path(str(ROOT / 'tools/codex-sandbox/codex-sandbox'))['image_sources']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / 'tools/codex-sandbox/image/Dockerfile'
            dockerfile.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / dockerfile.relative_to(root), dockerfile)
            runtime = ['tools/agent-split/bb', 'tools/agent-split/src/scripts/temp.clj',
                       'libexec/agent-wrappers/jj']
            noise = ['tools/agent-split/tests/test.clj', 'tools/agent-split/README.md',
                     'libexec/agent-wrappers/__pycache__/jj.pyc']
            for name in runtime + noise:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            with patch.dict(sources.__globals__, DOTFILES=root):
                selected = set(map(str, sources()))
            self.assertTrue(set(runtime) <= selected)
            self.assertFalse(set(noise) & selected)

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
            for name in ('Dockerfile', 'server.py', 'forward.py'):
                path = root / 'tools/zulip-proxy' / name
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
