"""The live runtime probe must build the Pi commit it checks."""

import json
from pathlib import Path
import runpy
import subprocess
import threading
import unittest
from unittest import mock


class ImageRuntimeIntegrationTest(unittest.TestCase):
    def test_combined_probe_keeps_each_required_check(self):
        check = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['check_guest']
        revision = 'b' * 40
        checksum = 'a' * 64
        valid = [f'{checksum}  /opt/agent-tools/libexec/jj', 'v24.3.0', revision,
                 'development-version', '1.3.14', 'bun-test-ok', 'wrapped-command-probe-ok']
        cases = [('valid', valid, False)]
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
            cases.append((name, changed, True))
        cases.extend([
            ('missing wrapper test', valid[:-1], True),
            ('missing checksum', valid[1:], True),
        ])
        for name, output, rejected in cases:
            with self.subTest(name=name):
                if rejected:
                    with self.assertRaises(RuntimeError):
                        check(output, revision, 'v24.', checksum)
                else:
                    check(output, revision, 'v24.', checksum)

    def test_combined_probe_follows_selected_runtime_and_revision(self):
        check = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['check_guest']
        for major, revision, checksum in ((20, 'c' * 40, 'd' * 64), (24, 'e' * 40, 'f' * 64)):
            with self.subTest(major=major):
                output = [f'{checksum}  /opt/agent-tools/libexec/jj', f'v{major}.9.0', revision,
                          'another-development-version', '1.3.14', 'bun-test-ok', 'wrapped-command-probe-ok']
                check(output, revision, f'v{major}.', checksum)

    def test_label_query_covers_both_images_and_rejects_wrong_or_missing_results(self):
        check = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['check_labels']
        for revision, tags in (('b' * 40, ['alpine:unique', 'debian:unique']),
                               ('c' * 40, ['renamed:one', 'other:two'])):
            for labels, rejected in (([revision, revision], False),
                                     (['wrong', revision], True),
                                     ([revision, 'wrong'], True),
                                     ([revision], True), ([], True)):
                with self.subTest(revision=revision, labels=labels):
                    result = mock.Mock(return_value='\n'.join(labels) + '\n')
                    with mock.patch.dict(check.__globals__, {'run': result}):
                        if rejected:
                            with self.assertRaises(RuntimeError):
                                check(tags, revision)
                        else:
                            check(tags, revision)
                    self.assertEqual(1, result.call_count)
                    self.assertEqual(tags, list(result.call_args.args[-2:]))

    def test_parallel_probes_finish_before_cleanup_on_success_and_failure(self):
        for failure in (None, 'jj-command', 'jj-output', 'alpine-command',
                        'alpine-output', 'alpine-checksum', 'debian-output'):
            with self.subTest(failure=failure):
                self.run_parallel_probe_case(failure)

    def run_parallel_probe_case(self, failure):
        main = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['main']
        revision, checksum = 'c' * 40, 'd' * 64
        tags = {}
        started = threading.Event()
        barrier = threading.Barrier(3, action=started.set)
        release = threading.Event()
        failed = threading.Event()
        cleaned = threading.Event()
        finished = {role: threading.Event() for role in ('jj', 'pi-alpine', 'pi-debian')}
        errors = []

        def build(selected_revision, selected_tags):
            self.assertEqual(revision, selected_revision)
            tags.update(selected_tags)

        def run(*command, **kwargs):
            if command[1:3] == ('image', 'inspect'):
                self.assertEqual([tags['pi-alpine'][0], tags['pi-debian'][0]], list(command[-2:]))
                return f'{revision}\n{revision}\n'
            if command[1:3] == ('image', 'ls'):
                return '\n'.join(aliases[1] for aliases in tags.values()) + '\n'
            self.assertEqual('run', command[1])
            tag = command[command.index('--entrypoint') + 2]
            role = next(role for role, aliases in tags.items() if aliases[0] == tag)
            try:
                barrier.wait(timeout=3)
                affected = failure is not None and failure.startswith(role.removeprefix('pi-'))
                if affected:
                    failed.set()
                    if failure.endswith('command'):
                        raise subprocess.CalledProcessError(17, command)
                else:
                    self.assertTrue(release.wait(timeout=3), 'test must release the other probes')
                if role == 'jj':
                    marker = 'failed' if affected else 'jj-colocated-ok'
                    return f'{checksum}  /trusted/bin/jj\n{marker}\n'
                node = 'v24.9.0' if role == 'pi-alpine' else 'v20.9.0'
                marker = 'failed' if affected and failure.endswith('output') else 'wrapped-command-probe-ok'
                binary = 'e' * 64 if affected and failure.endswith('checksum') else checksum
                return '\n'.join([f'{binary}  /opt/agent-tools/libexec/jj', node, revision,
                                  'development-version', '1.3.14', 'bun-test-ok', marker]) + '\n'
            finally:
                finished[role].set()

        def cleanup(command, **kwargs):
            cleaned.set()
            self.assertTrue(all(event.is_set() for event in finished.values()),
                            'cleanup must wait for every probe, including siblings of a failed probe')
            self.assertEqual({aliases[0] for aliases in tags.values()}, set(command[4:]))
            self.assertFalse({aliases[1] for aliases in tags.values()} & set(command[4:]))

        def invoke():
            try:
                main()
            except BaseException as error:
                errors.append(error)

        with mock.patch.dict(main.__globals__, {'build_images': build, 'run': run,
                                               'IMAGE_PREFIX': 'renamed-runtime'}), \
                mock.patch('sys.argv', ['integration', '--expected-revision', revision]), \
                mock.patch('subprocess.run', side_effect=cleanup):
            thread = threading.Thread(target=invoke)
            thread.start()
            try:
                self.assertTrue(started.wait(timeout=3), 'all three probes must overlap')
                if failure is not None:
                    self.assertTrue(failed.wait(timeout=3))
                    self.assertFalse(cleaned.wait(timeout=0.05), 'cleanup raced unfinished probes')
            finally:
                release.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        if failure is None:
            self.assertEqual([], errors)
        else:
            self.assertEqual(1, len(errors))
            expected = subprocess.CalledProcessError if failure.endswith('command') else RuntimeError
            self.assertIsInstance(errors[0], expected)
        self.assertTrue(cleaned.is_set())

    def test_bake_preserves_revisions_aliases_and_the_shared_jj_dependency(self):
        build = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['build_images']
        for revision, prefix in (('b' * 40, 'test'), ('c' * 40, 'renamed')):
            with self.subTest(revision=revision):
                tags = {role: (f'{prefix}-{role}:unique', f'{prefix}-{role}:cache')
                        for role in ('jj', 'pi-alpine', 'pi-debian')}
                release = {'JJ_AMD64_URL': 'https://example.invalid/selected-jj',
                           'JJ_AMD64_SHA256': 'd' * 64}
                captured = []

                def consume(command, *, cwd, check):
                    self.assertEqual(['docker', 'buildx', 'bake', '--file'], command[:4])
                    self.assertIn('--load', command)
                    self.assertTrue(check)
                    path = Path(command[4])
                    captured.append(path)
                    definition = json.loads(path.read_text())
                    targets = definition['target']
                    self.assertEqual(set(targets), set(definition['group']['default']['targets']))
                    by_alias = {target['tags'][0]: (name, target) for name, target in targets.items()}
                    self.assertEqual({value[0] for value in tags.values()}, set(by_alias))
                    jj_name, jj = by_alias[tags['jj'][0]]
                    self.assertEqual(release, jj['args'])
                    for role, aliases in tags.items():
                        _, target = by_alias[aliases[0]]
                        self.assertEqual(list(aliases), target['tags'])
                        if role == 'jj':
                            continue
                        self.assertEqual(revision, target['args']['PI_REVISION'])
                        dependency = target['args']['JJ_IMAGE']
                        self.assertEqual(f'target:{jj_name}', target['contexts'][dependency])
                    alpine = by_alias[tags['pi-alpine'][0]][1]
                    debian = by_alias[tags['pi-debian'][0]][1]
                    self.assertNotIn('BASE_IMAGE', alpine['args'])
                    self.assertEqual('node:20-bookworm-slim', debian['args']['BASE_IMAGE'])

                with mock.patch.dict(build.__globals__, {'jj_release_args': lambda: release}), \
                        mock.patch('subprocess.run', side_effect=consume):
                    build(revision, tags)
                self.assertEqual(1, len(captured))
                self.assertFalse(captured[0].parent.exists())

    def test_bake_failure_removes_the_definition_and_propagates_the_error(self):
        build = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['build_images']
        tags = {role: (f'{role}:unique', f'{role}:cache') for role in ('jj', 'pi-alpine', 'pi-debian')}
        error = subprocess.CalledProcessError(17, ['docker', 'buildx', 'bake'])
        with mock.patch('subprocess.run', side_effect=error) as run:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                build('b' * 40, tags)
            command = run.call_args.args[0]
            definition = Path(command[command.index('--file') + 1])
        self.assertIs(error, caught.exception)
        self.assertFalse(definition.parent.exists())

    def test_failed_bake_cleans_run_aliases_without_running_probes_or_removing_caches(self):
        main = runpy.run_path(str(Path(__file__).with_name('image_runtime_integration.py')))['main']
        revision = 'b' * 40
        build = mock.Mock(side_effect=subprocess.CalledProcessError(17, ['docker', 'buildx', 'bake']))
        probe = mock.Mock()
        with mock.patch.dict(main.__globals__, {'build_images': build, 'run': probe,
                                               'IMAGE_PREFIX': 'renamed-runtime'}), \
                mock.patch('sys.argv', ['integration', '--expected-revision', revision]), \
                mock.patch('subprocess.run') as cleanup:
            with self.assertRaises(subprocess.CalledProcessError):
                main()
        self.assertEqual(revision, build.call_args.args[0])
        tags = build.call_args.args[1]
        command = cleanup.call_args.args[0]
        self.assertEqual(['docker', 'image', 'rm', '-f'], command[:4])
        self.assertEqual({aliases[0] for aliases in tags.values()}, set(command[4:]))
        self.assertFalse({aliases[1] for aliases in tags.values()} & set(command[4:]))
        probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
