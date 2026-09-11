"""Existing image builders key copied inputs rather than local build output."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ImageBuilderTest(unittest.TestCase):
    def test_jj_key_changes_with_sources_but_not_local_build_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = root / '.agents/sandbox/jj-proxy-image'
            builder.parent.mkdir(parents=True)
            shutil.copy2(ROOT / '.agents/sandbox/jj-proxy-image', builder)
            helper = root / 'tools/codex-sandbox/sandbox-image'
            helper.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'tools/codex-sandbox/owned_images.py', helper.parent / 'owned_images.py')
            shutil.copyfile(ROOT / 'tools/codex-sandbox/tests/fixtures/print-builder-arguments.sh', helper)
            helper.chmod(0o755)
            for name in ('Dockerfile', 'Cargo.toml', 'Cargo.lock', 'src/main.rs', 'jj.toml', 'agent-split-editor'):
                path = root / 'tools/jj-proxy' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            (root / 'config').mkdir()
            (root / 'config/gitignore').write_text('ignored\n')
            def key():
                result = subprocess.run([str(builder)], capture_output=True, text=True, check=True)
                arguments = result.stdout.splitlines()
                return arguments[arguments.index('--tag') + 1]
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


if __name__ == '__main__':
    unittest.main()
