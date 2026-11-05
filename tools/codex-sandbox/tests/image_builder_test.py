"""Existing image builders key copied inputs rather than local build output."""

import importlib.util
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ImageBuilderTest(unittest.TestCase):
    def test_jj_key_changes_with_sources_but_not_local_build_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module_path = root / 'tools/codex-sandbox/owned_images.py'
            module_path.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'tools/codex-sandbox/owned_images.py', module_path)
            for name in ('Cargo.toml', 'Cargo.lock', 'src/main.rs', 'jj.toml', 'policy.toml', 'agent-split-editor'):
                path = root / 'tools/jj-proxy' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            dockerfile = root / 'tools/jj-proxy/Dockerfile'
            dockerfile.parent.mkdir(parents=True, exist_ok=True)
            dockerfile.write_text(
                'COPY tools/jj-proxy/Cargo.toml ./\\n'
                'COPY tools/jj-proxy/Cargo.lock ./\\n'
                'COPY tools/jj-proxy/jj.toml ./\\n'
                'COPY tools/jj-proxy/policy.toml ./\\n'
                'COPY tools/jj-proxy/src ./src\\n'
                'COPY config/gitignore /trusted/gitignore\\n'
                'COPY tools/jj-proxy/agent-split-editor /trusted/bin/agent-split-editor\\n'
            )
            (root / 'config').mkdir()
            (root / 'config/gitignore').write_text('ignored\n')
            shutil.copyfile(ROOT / 'config/mise.lock', root / 'config/mise.lock')
            release = tomllib.loads((root / 'config/mise.lock').read_text())['tools']['aqua:jj-vcs/jj'][0]
            expected_url = release['platforms.linux-x64']['url']
            spec = importlib.util.spec_from_file_location('fixture_owned_images', module_path)
            assert spec is not None and spec.loader is not None
            owned_images = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(owned_images)

            def key():
                image = owned_images.declaration(['jj'], platform='linux/amd64')['target']['jj']
                self.assertEqual(expected_url, image['args']['JJ_AMD64_URL'])
                return image['tags'][0]
            first = key()
            artifact = root / 'tools/jj-proxy/target/debug/artifact'
            artifact.parent.mkdir(parents=True)
            artifact.write_text('local build output')
            self.assertEqual(key(), first)
            source = root / 'tools/jj-proxy/src/new.rs'
            source.write_text('new source')
            self.assertNotEqual(key(), first)
            source.unlink()
            self.assertEqual(key(), first)
            (root / 'tools/jj-proxy/Cargo.lock').write_text('changed dependency')
            self.assertNotEqual(key(), first)
            policy = root / 'tools/jj-proxy/policy.toml'
            policy.write_text('changed policy')
            self.assertNotEqual(key(), first)


if __name__ == '__main__':
    unittest.main()
