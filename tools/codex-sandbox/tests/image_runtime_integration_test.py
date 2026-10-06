"""The live runtime probe must build the Pi commit it checks."""

from pathlib import Path
import runpy
import unittest
from unittest import mock


class ImageRuntimeIntegrationTest(unittest.TestCase):
    def test_runtime_builds_receive_the_selected_pi_commit(self):
        build = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['build']
        revision = 'b' * 40
        for base in (None, 'node:20-bookworm-slim'):
            with self.subTest(base=base), mock.patch('subprocess.run') as run:
                build('test-image', revision, base)
                command = run.call_args.args[0]
                build_args = [command[index + 1] for index, argument in enumerate(command)
                              if argument == '--build-arg']
                expected = [f'PI_REVISION={revision}']
                if base is not None:
                    expected.append(f'BASE_IMAGE={base}')
                self.assertEqual(expected, build_args)
                self.assertTrue(run.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
