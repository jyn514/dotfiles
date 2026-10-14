"""The live runtime probe must build the Pi commit it checks."""

from pathlib import Path
import runpy
import unittest
from unittest import mock


class ImageRuntimeIntegrationTest(unittest.TestCase):
    def test_combined_probe_keeps_each_required_check(self):
        check = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['check_guest']
        revision = 'b' * 40
        checksum = 'a' * 64
        valid = [f'{checksum}  /opt/agent-tools/libexec/jj', 'v24.3.0', revision,
                 'development-version', '1.3.14', 'bun-test-ok', 'wrapped-command-probe-ok']
        cases = [('valid', valid, revision, False)]
        for index, value, name in (
            (0, 'c' * 64 + '  /opt/agent-tools/libexec/jj', 'different proxy binary'),
            (1, 'v20.3.0', 'wrong Node major'),
            (2, 'c' * 40, 'wrong embedded revision'),
            (4, '1.2.0', 'wrong Bun version'),
            (5, 'bun-test-failed', 'failed Bun test'),
            (6, 'wrapper-failed', 'failed wrapper test'),
        ):
            changed = valid.copy()
            changed[index] = value
            cases.append((name, changed, revision, True))
        cases.extend([
            ('wrong image label', valid, 'c' * 40, True),
            ('missing wrapper test', valid[:-1], revision, True),
            ('missing checksum', valid[1:], revision, True),
        ])
        for name, output, label, rejected in cases:
            with self.subTest(name=name):
                result = mock.Mock(side_effect=[label + '\n', '\n'.join(output) + '\n'])
                with mock.patch.dict(check.__globals__, {'run': result}):
                    if rejected:
                        with self.assertRaises(RuntimeError):
                            check('guest', revision, 'v24.', checksum)
                    else:
                        check('guest', revision, 'v24.', checksum)

    def test_combined_probe_follows_selected_runtime_and_revision(self):
        check = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['check_guest']
        for major, revision, checksum in ((20, 'c' * 40, 'd' * 64), (24, 'e' * 40, 'f' * 64)):
            with self.subTest(major=major):
                output = [f'{checksum}  /opt/agent-tools/libexec/jj', f'v{major}.9.0', revision,
                          'another-development-version', '1.3.14', 'bun-test-ok', 'wrapped-command-probe-ok']
                result = mock.Mock(side_effect=[revision + '\n', '\n'.join(output) + '\n'])
                with mock.patch.dict(check.__globals__, {'run': result}):
                    check('renamed-guest', revision, f'v{major}.', checksum)

    def test_runtime_builds_receive_the_selected_pi_commit(self):
        build = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['build']
        revision = 'b' * 40
        for base in (None, 'node:20-bookworm-slim'):
            with self.subTest(base=base), mock.patch('subprocess.run') as run:
                build('test-image', revision, base, jj_image='proxy@sha256:' + 'a' * 64,
                      cache_tag='test-image:cache')
                command = run.call_args.args[0]
                build_args = [command[index + 1] for index, argument in enumerate(command)
                              if argument == '--build-arg']
                expected = [f'PI_REVISION={revision}', 'JJ_IMAGE=proxy@sha256:' + 'a' * 64]
                if base is not None:
                    expected.append(f'BASE_IMAGE={base}')
                self.assertEqual(expected, build_args)
                self.assertTrue(run.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
