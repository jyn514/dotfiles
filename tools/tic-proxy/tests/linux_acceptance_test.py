"""Offline workflow safety tests; opt-in native components are NOT host acceptance."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import linux_acceptance as acceptance
import linux_acceptance_guest as guest_checker


class LinuxAcceptanceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tic-workflow-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_fresh_git_linked_fixture_has_standalone_main_and_synthetic_local_configuration(self):
        with mock.patch.dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='user.email',
                             GIT_CONFIG_VALUE_0='must-not-inherit@example.invalid'):
            fixture = acceptance.Fixture(self.root)
        fixture.prepare()
        fixture.guard()
        self.assertTrue((fixture.main / '.jj').is_dir())
        self.assertFalse((fixture.linked / '.jj').exists())
        self.assertTrue(fixture.git(fixture.main, 'rev-parse', '--verify', 'HEAD'))
        self.assertEqual('linux-acceptance@example.invalid', fixture.git(fixture.linked, 'config', 'user.email'))
        self.assertTrue(fixture.git(fixture.main, 'config', 'meta.namespace').startswith('acceptance-'))
        # Consume the declaration with the existing producer/parser rather than
        # assuming our JSON constitutes supported accepted launch authority.
        spec = importlib.util.spec_from_file_location('workflow_policy', acceptance.DOTFILES / 'tools/codex-sandbox/sandbox-proxies.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        parsed = policy.load_optional_manifest(fixture.main)
        self.assertTrue(parsed['capabilities']['tic'])
        self.assertFalse(parsed['capabilities']['zulip'])
        self.assertFalse(parsed['capabilities']['nested-containers'])
        with self.assertRaisesRegex(RuntimeError, 'fresh'):
            fixture.prepare()

    def test_wrong_common_root_stops_before_native_invocation(self):
        fixture = acceptance.Fixture(self.root)
        fixture.prepare()
        original = fixture.git
        def wrong(cwd, *argv):
            if '--git-common-dir' in argv:
                return str(self.root / 'unrelated')
            return original(cwd, *argv)
        with mock.patch.object(fixture, 'git', side_effect=wrong), mock.patch.object(fixture, 'command', wraps=fixture.command) as command:
            with self.assertRaisesRegex(RuntimeError, 'common authority'):
                fixture.ti('/must-not-execute', fixture.linked, 'new', '--title', 'wrong')
        self.assertFalse(any(str(call.args[1][0]) == '/must-not-execute' for call in command.call_args_list))

    def test_unrelated_fixture_marker_stops_before_native_invocation(self):
        fixture = acceptance.Fixture(self.root)
        fixture.prepare()
        (fixture.main / 'fixture.json').write_text('{"fixture_nonce":"historical-smoke"}\n')
        with self.assertRaisesRegex(RuntimeError, 'not this workflow'):
            fixture.ti('/must-not-execute', fixture.main, 'new', '--title', 'wrong fixture')

    def test_independent_linked_store_is_preserved_and_refused(self):
        fixture = acceptance.Fixture(self.root)
        fixture.prepare()
        independent = fixture.main / '.git/worktrees/linked/git-meta.sqlite'
        independent.write_bytes(b'never adopt or reset this independent store')
        with self.assertRaisesRegex(RuntimeError, 'independent linked store'):
            fixture.ti('/must-not-execute', fixture.main, 'list')
        self.assertEqual(b'never adopt or reset this independent store', independent.read_bytes())

    def test_guest_claim_prevents_replay_even_after_preflight_failure(self):
        (self.root / 'evidence').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'checker/cwd'):
            guest_checker.run(self.root)
        self.assertFalse(json.loads((self.root / 'evidence/guest.json').read_text())['passed'])
        with self.assertRaises(FileExistsError):
            guest_checker.run(self.root)

    def test_guest_container_cannot_claim_actual_host_acceptance_or_create_fixture(self):
        target = self.root / 'must-not-create'
        with mock.patch.dict(os.environ, DOTFILES_SANDBOX='1'):
            with self.assertRaisesRegex(RuntimeError, 'actual host/provider'):
                acceptance.run_host(self.root / 'missing-bundle', Path('/missing-pi'), target)
        self.assertFalse(target.exists())

    def test_default_cli_needs_no_bundle_and_explicit_override_is_preserved(self):
        for extra, expected in (([], None), (['--bundle', str(self.root)], self.root)):
            with self.subTest(extra=extra), mock.patch.object(sys, 'argv', [
                    'linux_acceptance.py', '--actual-linux-host', *extra]), mock.patch.object(
                    acceptance, 'run_host') as run:
                self.assertEqual(0, acceptance.main())
                self.assertEqual(expected, run.call_args.args[0])

    def test_automatic_selection_uses_production_resolver_state_and_runtime_platform(self):
        # Load the real producer, substituting only the provider and artifact I/O.
        # Changing its returned manifest or runtime platform must change selection
        # without editing this consumer's cache/source-key rules (there are none).
        launcher = acceptance.runpy.run_path(str(acceptance.DOTFILES / 'tools/codex-sandbox/codex-sandbox'))
        import tic_artifact
        runtime = mock.Mock()
        launcher['image_runtime'] = mock.Mock(return_value=runtime)
        for index, platform in enumerate(('linux/arm64', 'linux/amd64')):
            selected = self.root / f'producer-selected-{index}'
            runtime.build_platform.return_value = platform
            build = SimpleNamespace(broker_executable=selected / 'host/tic-broker')
            with self.subTest(platform=platform), mock.patch.dict(os.environ, HOME=str(self.root)), mock.patch.object(
                    acceptance.runpy, 'run_path', return_value=launcher), mock.patch.object(
                    tic_artifact, 'resolve_bundle', return_value=selected / 'manifest.json') as resolve, mock.patch.object(
                    launcher['InstalledTicBuild'], 'load', return_value=build) as load, mock.patch(
                    'sys.stderr', new_callable=io.StringIO) as progress:
                self.assertEqual(selected, acceptance.select_bundle())
                self.assertEqual(self.root / '.cache/codex-sandbox/tic', resolve.call_args.args[0])
                self.assertEqual(platform, resolve.call_args.args[1])
                self.assertTrue(callable(resolve.call_args.args[3]))  # ordinary cold-cache provisioner
                load.assert_called_once_with(selected / 'manifest.json')
                self.assertIn('cold cache may fetch and build', progress.getvalue())
                self.assertNotIn(str(selected), progress.getvalue())
        self.assertEqual(2, launcher['image_runtime'].call_count)
        self.assertFalse((self.root / '.cache').exists())

    def test_resolver_failure_stops_once_before_any_fixture_without_retry(self):
        target = self.root / 'must-not-create'
        with mock.patch.dict(os.environ, DOTFILES_SANDBOX='0'), mock.patch.object(
                acceptance.sys.stdin, 'isatty', return_value=True), mock.patch.object(
                acceptance.sys.stdout, 'isatty', return_value=True), mock.patch.object(
                acceptance, 'select_bundle', side_effect=RuntimeError('normal resolver unavailable')) as select, mock.patch.object(
                acceptance, 'Fixture') as fixture:
            with self.assertRaisesRegex(RuntimeError, 'normal resolver unavailable'):
                acceptance.run_host(None, Path('/unused-pi'), target)
            select.assert_called_once_with(None)
            fixture.assert_not_called()
        self.assertFalse(target.exists())

    def test_explicit_bundle_skips_launcher_but_still_requires_actual_host_cache(self):
        with mock.patch.object(acceptance.runpy, 'run_path') as load:
            self.assertEqual(self.root, acceptance.select_bundle(self.root))
        load.assert_not_called()
        for protected in (False, True):
            home = self.root / 'owned-home'
            bundle = home / '.cache/codex-sandbox/tic/selected' if protected else self.root
            bundle.mkdir(parents=True, exist_ok=True)
            destination = self.root / 'acceptance-output'
            with self.subTest(protected=protected), mock.patch.dict(os.environ, DOTFILES_SANDBOX='0'), mock.patch.object(
                    acceptance.sys.stdin, 'isatty', return_value=True), mock.patch.object(
                    acceptance.sys.stdout, 'isatty', return_value=True), mock.patch.object(
                    acceptance.Path, 'home', return_value=home), mock.patch.object(
                    acceptance, 'protected_bundle', return_value=(b'{}', {'build': {'host_platform': acceptance.host_platform()}}, None)), mock.patch.object(
                    acceptance.Fixture, 'prepare', side_effect=RuntimeError('fixture preparation reached')) as prepare, mock.patch.object(
                    acceptance.runpy, 'run_path') as load, mock.patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError, 'fixture preparation reached' if protected else 'actual launcher protected cache'):
                    acceptance.run_host(bundle, Path('/unused-pi'), destination)
                self.assertEqual(protected, prepare.called)
                load.assert_not_called()
            self.assertEqual(protected, destination.exists())
            if protected:
                reports = list(destination.glob('*/receipt.json'))
                self.assertEqual(1, len(reports))
                report = json.loads(reports[0].read_text())
                self.assertFalse(report['passed'])
                self.assertEqual('preparing', report['phase'])
                self.assertEqual('fixture preparation reached', report['failure'])
                self.assertIn('no lifecycle or interleaving proof', report['scope'])

    def test_host_boundaries_precede_any_selection_provider_or_cache_effects(self):
        # Independently deny the guest and terminal boundaries, both with and
        # without an override. Even resolving a missing override must wait.
        for sandbox, tty, message in (('1', True, 'actual host/provider'),
                                      ('0', False, 'interactive terminal')):
            for bundle in (None, self.root / 'missing-bundle'):
                with self.subTest(sandbox=sandbox, bundle=bundle), mock.patch.dict(
                        os.environ, DOTFILES_SANDBOX=sandbox), mock.patch.object(
                        acceptance.sys.stdin, 'isatty', return_value=tty), mock.patch.object(
                        acceptance.sys.stdout, 'isatty', return_value=tty), mock.patch.object(
                        acceptance, 'select_bundle') as select, mock.patch.object(
                        acceptance.runpy, 'run_path') as load:
                    with self.assertRaisesRegex(RuntimeError, message):
                        acceptance.run_host(bundle, Path('/unused-pi'), self.root / 'must-not-create')
                    select.assert_not_called()
                    load.assert_not_called()
        self.assertFalse((self.root / 'must-not-create').exists())

    def test_failed_startup_guest_requires_unavailable_guard_and_keeps_tools_usable(self):
        fixture = acceptance.Fixture(self.root)
        fixture.prepare()
        original_run = subprocess.run
        original_cwd = Path.cwd()
        def guarded(argv, **kwargs):
            if argv[0] == 'ti':
                return subprocess.CompletedProcess(argv, 125, '', 'TicGit unavailable for this session')
            return original_run(argv, **kwargs)
        try:
            os.chdir(fixture.main)
            with mock.patch.dict(os.environ, DOTFILES_SANDBOX='1'), mock.patch.object(
                    guest_checker.shutil, 'which', return_value='/libexec/sandbox-wrappers/ti'), mock.patch.object(
                    guest_checker, '__file__', str(fixture.main / 'check_guest.py')), mock.patch.object(
                    guest_checker.subprocess, 'run', side_effect=guarded), mock.patch('builtins.print'):
                guest_checker.run(fixture.main, failed=True)
        finally:
            os.chdir(original_cwd)
        report = json.loads((fixture.main / 'evidence/guest.json').read_text())
        self.assertTrue(report['passed'])
        self.assertIn('Pi guest tools remain usable', report['commands'][-1]['stdout'])
        self.assertFalse((fixture.main / '.git/git-meta.sqlite').exists())

    def test_interactive_uses_ordinary_terminal_and_retains_exit_or_launch_failure(self):
        for index, exit_code in enumerate((0, 1, None)):
            root = self.root / str(index)
            main = root / 'main'
            main.mkdir(parents=True)
            fixture = SimpleNamespace(root=root, main=main)
            with self.subTest(exit_code=exit_code), mock.patch.object(
                    acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess([], exit_code),
                    side_effect=OSError('cannot launch TEST Pi') if exit_code is None else None) as run:
                if exit_code == 0:
                    acceptance.interactive(fixture, Path('/ordinary/bin/pi'))
                else:
                    with self.assertRaisesRegex((OSError, RuntimeError), 'cannot launch|exited unsuccessfully'):
                        acceptance.interactive(fixture, Path('/ordinary/bin/pi'))
                self.assertEqual(['/ordinary/bin/pi', '--no-session', '@' + str(main / 'acceptance-prompt.md')],
                                 run.call_args.args[0])
                self.assertEqual(main, run.call_args.kwargs['cwd'])
                self.assertNotIn('capture_output', run.call_args.kwargs)
                self.assertNotIn('stdin', run.call_args.kwargs)
                self.assertNotIn('stdout', run.call_args.kwargs)
            report = json.loads((root / 'pi-exit.json').read_text())
            self.assertEqual(exit_code == 0, report['passed'])
            self.assertEqual(exit_code, report.get('exit'))
            self.assertEqual(exit_code != 0, 'failure' in report)

    def test_guest_boundary_failure_output_is_plain_and_never_claims_acceptance(self):
        for extra in ([], ['--bundle', str(self.root)]):
            with self.subTest(extra=extra):
                output = subprocess.run([sys.executable, str(TESTS / 'linux_acceptance.py'),
                                         '--actual-linux-host', *extra],
                                        env=dict(os.environ, DOTFILES_SANDBOX='1'),
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(1, output.returncode)
                self.assertEqual('', output.stdout)
                self.assertEqual(1, output.stderr.count('STOP:'))
                self.assertIn('guest container is not the actual host/provider', output.stderr)
                self.assertIn('No automatic retry or provider stop', output.stderr)
                self.assertNotIn('Selecting', output.stderr)
                self.assertNotIn('PASS', output.stderr)

    def test_documented_script_help_works_in_clean_interpreter_without_service_effects(self):
        output = subprocess.run([sys.executable, str(TESTS / 'linux_acceptance.py'), '--help'],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(0, output.returncode, output.stderr)
        self.assertIn('--actual-linux-host', output.stdout)
        help_text = ' '.join(output.stdout.split())
        self.assertIn('ordinary interactive', help_text)
        self.assertIn('optional actual protected cache bundle override', help_text)


@unittest.skipUnless(os.environ.get('TIC_LINUX_COMPONENT_BUNDLE'),
                     'opt in with TIC_LINUX_COMPONENT_BUNDLE; local native/client/broker only, NOT host Pi')
class LinuxAcceptanceNativeComponents(unittest.TestCase):
    def test_pinned_bundle_real_cli_shared_store_and_history_workflow(self):
        sys.path.insert(0, str(acceptance.DOTFILES / 'tools/codex-sandbox'))
        from bundle import stage_cache
        from tic_broker import InstalledTicBuild, TicBrokerLaunch
        destination = acceptance.DOTFILES / 'target/tic-acceptance/components'
        destination.mkdir(parents=True, exist_ok=True)
        import uuid
        root = destination / ('run-' + uuid.uuid4().hex)
        root.mkdir(mode=0o700)
        fixture = acceptance.Fixture(root)
        fixture.prepare()
        manifest = stage_cache(Path(os.environ['TIC_LINUX_COMPONENT_BUNDLE']).resolve(), root / 'protected-cache')
        build = InstalledTicBuild.load(manifest)
        native = build.native_executable
        host = {'title': 'component host-linked title'}
        host['id'] = fixture.ti(native, fixture.linked, 'new', '--title', host['title'], '--id-only')['stdout'].strip()
        namespace = fixture.git(fixture.main, 'config', 'meta.namespace')
        launch = TicBrokerLaunch(build, workspace=fixture.main, common_dir=fixture.main / '.git',
                                 user_name='Component Guest', user_email='component@example.invalid', namespace=namespace).start()
        try:
            environment = dict(fixture.environment, **launch.environment())
            commands = []
            def client(*argv):
                output = subprocess.run([str(build.guest_client_executable), *argv], cwd=fixture.main,
                                        env=environment, text=True, capture_output=True, timeout=50)
                item = dict(argv=list(argv), exit=output.returncode,
                            stdout=output.stdout, stderr=output.stderr)
                commands.append(item)
                return item
            shown = client('show', host['id'], '--json')
            self.assertEqual(0, shown['exit'], shown)
            self.assertIn(host['title'], shown['stdout'])
            comment = 'actual component client comment α'
            changed = client('comment', '--ticket', host['id'], comment)
            self.assertEqual(0, changed['exit'], changed)
            # Independently dispatched local writer loops; this smoke test
            # checks their successful results, not the timing of interleaving.
            import threading
            barrier = threading.Barrier(2)
            def human():
                barrier.wait(timeout=5)
                return [dict(title=f'host concurrent {i}', **fixture.ti(native, fixture.linked,
                        'new', '--title', f'host concurrent {i}', '--id-only', success=False)) for i in range(4)]
            def guest():
                barrier.wait(timeout=5)
                return [dict(title=f'guest concurrent {i}', **client('new', '--title', f'guest concurrent {i}', '--id-only'))
                        for i in range(4)]
            with ThreadPoolExecutor(max_workers=2) as workers:
                one, two = workers.submit(human), workers.submit(guest)
                host_writes, guest_writes = one.result(), two.result()
            for item in host_writes + guest_writes:
                if item['exit']:
                    self.assertRegex(item['stderr'].lower(), 'locked|busy')
            acceptance.verify_shared(fixture, native, host, {'comment': comment, 'writes': guest_writes}, host_writes)
            with self.assertRaisesRegex(RuntimeError, 'guest change absent'):
                acceptance.verify_shared(fixture, native, host, {'comment': 'not actually persisted', 'writes': guest_writes}, host_writes)
            # Delete real log rows only in this newly owned component store.
            # First require native history itself to detect the loss; then replay
            # the previously recorded, valid CLI histories so SQLite must reject
            # independently rather than relying on agreement between renderers.
            successful = [item for item in host_writes + guest_writes if item['exit'] == 0]
            recorded = {(cwd, item['stdout'].strip()): fixture.ti(
                native, cwd, 'history', '--ticket', item['stdout'].strip(), '--json')
                for item in successful for cwd in (fixture.main, fixture.linked)}
            original_ti = fixture.ti
            def recorded_history(executable, cwd, *argv, **kwargs):
                if argv[0] == 'history' and (cwd, argv[2]) in recorded:
                    return recorded[cwd, argv[2]]
                return original_ti(executable, cwd, *argv, **kwargs)
            negatives = []
            for label, candidates, field in (('host missing created-by', host_writes, 'created-by'),
                                               ('guest missing all creation history', guest_writes, None)):
                self.assertTrue(any(item['exit'] == 0 for item in candidates), label)
                victim = next(item['stdout'].strip() for item in candidates if item['exit'] == 0)
                prefix = f'ticgit:tickets:{victim}:'
                with sqlite3.connect(fixture.main / '.git/git-meta.sqlite') as connection:
                    rows = connection.execute(
                        'select rowid,target_type,target_value,key,value,value_type,operation,email,timestamp '
                        'from metadata_log where key like ?', (prefix + '%',)).fetchall()
                    removed = [row for row in rows if field is None or row[3] == prefix + field]
                    self.assertEqual(5 if field is None else 1, len(removed))
                    connection.executemany('delete from metadata_log where rowid = ?', [(row[0],) for row in removed])
                    connection.commit()
                    try:
                        with self.assertRaisesRegex(RuntimeError, 'native creation history missing') as cli_error:
                            acceptance.verify_shared(fixture, native, host, {'comment': comment, 'writes': guest_writes}, host_writes)
                        with mock.patch.object(fixture, 'ti', side_effect=recorded_history):
                            with self.assertRaisesRegex(RuntimeError, 'SQLite creation history missing') as sql_error:
                                acceptance.verify_shared(fixture, native, host, {'comment': comment, 'writes': guest_writes}, host_writes)
                        negatives.append(dict(case=label, ticket_id=victim, removed_events=len(removed),
                                              native_rejected=str(cli_error.exception), sqlite_rejected=str(sql_error.exception)))
                    finally:
                        connection.executemany(
                            'insert into metadata_log (rowid,target_type,target_value,key,value,value_type,operation,email,timestamp) '
                            'values (?,?,?,?,?,?,?,?,?)', removed)
                        connection.commit()
            # Restoring the exact rows (including rowids) must restore acceptance.
            acceptance.verify_shared(fixture, native, host, {'comment': comment, 'writes': guest_writes}, host_writes)
            publish = guest_checker.publish
            publish(root / 'history-oracle-negative.json', negatives)
            publish(root / 'component-receipt.json', dict(scope='local native/client/broker; NOT actual Pi/provider',
                    manifest=json.loads(manifest.read_text()), commands=commands, passed=True))
        finally:
            self.assertFalse(launch.stop().remaining)
        after = fixture.ti(native, fixture.linked, 'new', '--title', 'native works after component stop', '--id-only')
        self.assertEqual(0, after['exit'])
        print(f'PASS: native components only; retained evidence at {root}')
