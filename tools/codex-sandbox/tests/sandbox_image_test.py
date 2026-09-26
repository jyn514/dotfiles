"""Project resolvers submit fresh Bake input to the admitted engine."""

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('sandbox_image', str(ROOT / 'sandbox-image'))
spec = importlib.util.spec_from_loader(loader.name, loader)
sandbox_image = importlib.util.module_from_spec(spec)
loader.exec_module(sandbox_image)


class ProjectBakeTest(unittest.TestCase):
    def test_cancellation_joins_detached_builder_and_releases_capture(self):
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                process = subprocess.Popen([
                    sys.executable, '-B', str(ROOT / 'tests/sandbox_image_cancel_fixture.py'), directory,
                ], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, start_new_session=True)
                child = None
                try:
                    deadline = time.monotonic() + 10
                    marker = root / 'child'
                    while time.monotonic() < deadline and process.poll() is None:
                        if marker.exists() and marker.read_text():
                            child = int(marker.read_text())
                            break
                        time.sleep(0.01)
                    self.assertIsNotNone(child, 'detached builder did not start')
                    process.send_signal(signum)
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 128 + signum, stderr)
                    self.assertEqual(stdout, '')
                    listing = subprocess.run(['ps', '-axo', 'pid=,stat='], capture_output=True,
                                             text=True, check=True).stdout.splitlines()
                    self.assertFalse(any(fields[0] == str(child) and not fields[1].startswith('Z')
                                         for line in listing if len(fields := line.split()) == 2))
                    self.assertEqual(list(root.glob('capture-*')), [])
                finally:
                    if process.poll() is None:
                        process.kill()
                    if child is not None:
                        try:
                            os.kill(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.communicate(timeout=10)

    def invoke(self, runtime, mode='resolve'):
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', [
            'sandbox-image', 'bake', '--platform', 'linux/arm64',
            '--mode', mode, 'base', 'bug',
        ]), mock.patch.object(sys, 'stdin', io.StringIO('target "base" {}\n')), \
                mock.patch.object(sys, 'stdout', output), \
                mock.patch.object(sandbox_image, 'image_runtime', return_value=runtime):
            sandbox_image.main()
        return json.loads(output.getvalue())

    def test_fresh_input_and_lifecycle_reach_bake_without_loading_repository_policy(self):
        runtime = mock.Mock(provider='lima-docker')
        runtime.build_platform.return_value = 'linux/arm64'
        images = {'base': 'sha256:' + '1' * 64, 'bug': 'sha256:' + '2' * 64}
        with mock.patch('bake.resolve', return_value=images) as resolve, \
                mock.patch.object(sandbox_image, 'policy_module', side_effect=AssertionError('recursive policy load')):
            for mode in ('resolve', 'refresh', 'clean'):
                self.assertEqual(self.invoke(runtime, mode), {'version': 1, 'images': images})
                resolve.assert_called_with(
                    runtime, Path.cwd(), ['base', 'bug'],
                    declaration='target "base" {}\n', operation=mode,
                )

    def test_wrong_engine_or_platform_never_invokes_bake(self):
        for provider, platform in [('container', 'linux/arm64'), ('lima-docker', 'linux/amd64')]:
            runtime = mock.Mock(provider=provider)
            runtime.build_platform.return_value = platform
            with self.subTest(provider=provider, platform=platform), \
                    mock.patch('bake.resolve') as resolve, self.assertRaises(ValueError):
                self.invoke(runtime)
            resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
