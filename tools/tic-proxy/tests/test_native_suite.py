"""Opt-in route from dev/test discovery to the complete pinned Cargo suite.

Set TIC_PROXY_NATIVE_REPOSITORY to an owned local fork containing native-revision.
The build helper archives the Git object; mutable working-tree files are not input.
For retained disposable actual-native store checks instead, set TIC_STORE_BUNDLE
and TIC_STORE_EVIDENCE. This route does not build or launch an actual provider.
"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TicNativeSuite(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('TIC_PROXY_NATIVE_REPOSITORY'),
                         'opt in with TIC_PROXY_NATIVE_REPOSITORY to build the pinned local fork')
    def test_complete_pinned_native_and_broker_suite(self):
        output = subprocess.run(
            [str(ROOT / 'build-local'), os.environ['TIC_PROXY_NATIVE_REPOSITORY'], 'test'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900,
        )
        evidence = ROOT.parents[1] / 'target/tic-proxy-build/discovered-native.log'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(output.stdout)
        self.assertEqual(output.returncode, 0, output.stdout)


@unittest.skipUnless(os.environ.get('TIC_STORE_BUNDLE'),
                     'opt in with TIC_STORE_BUNDLE for disposable actual-native store acceptance')
class NativeStoreAcceptance(unittest.TestCase):
    """Actual pinned native, optional local broker; no provider or real user store.

    Fixtures and raw command/response transcripts are retained under the explicit
    TIC_STORE_EVIDENCE directory. The supplied bundle's exact identities, not the
    mutable proxy checkout, describe runtime authority. No runtime source edits.
    """

    @classmethod
    def setUpClass(cls):
        import hashlib
        import json
        import sys
        import threading
        import uuid
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT.parent / 'codex-sandbox'))
        from bundle import PIN, stage_cache
        from tic_broker import InstalledTicBuild
        cls.json = json
        cls.lock = threading.Lock()
        cls.evidence = Path(os.environ['TIC_STORE_EVIDENCE']).resolve()
        cls.evidence.mkdir(parents=True, exist_ok=True)
        cls.run_root = cls.evidence / ('run-' + uuid.uuid4().hex)
        cls.run_root.mkdir(mode=0o700)
        bundle = Path(os.environ['TIC_STORE_BUNDLE']).resolve(strict=True)
        # Reuse the production copy/validation boundary, not writable build output.
        manifest = stage_cache(bundle, cls.run_root / 'protected-cache')
        cls.build = InstalledTicBuild.load(manifest)
        cls.native = cls.build.native_executable
        cls.authority = json.loads(manifest.read_bytes())
        if cls.authority['native_revision'] != PIN:
            raise AssertionError('This acceptance group requires the canonical native pin')
        cls.authority.update(input_bundle=str(bundle), staged_manifest=str(manifest),
                             manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                             scope='disposable Linux local native and loopback broker; no actual provider')
        (cls.run_root / 'authority.json').write_text(json.dumps(cls.authority, indent=2) + '\n')
        print('STORE_ACCEPTANCE_EVIDENCE=' + str(cls.run_root), flush=True)

    def record(self, value):
        with self.lock:
            with (self.root / 'transcript.jsonl').open('a') as stream:
                stream.write(self.json.dumps(value) + '\n')

    def setUp(self):
        self.root = self.run_root / self._testMethodName
        self.root.mkdir()
        self.main = self.root / 'main'
        self.linked = self.root / 'linked'
        self.common = self.main / '.git'
        self.ui = self.root / 'human-ui.json'
        self.environment = dict(PATH=os.environ['PATH'], HOME=str(self.root / 'home'),
            XDG_CONFIG_HOME=str(self.root / 'config'), XDG_STATE_HOME=str(self.root / 'state'),
            XDG_CACHE_HOME=str(self.root / 'cache'), GIT_CONFIG_NOSYSTEM='1',
            GIT_CONFIG_GLOBAL='/dev/null', TICGIT_STATE_FILE=str(self.ui), LANG='C.UTF-8')
        self.git(self.root, 'init', '-qb', 'main', str(self.main))
        self.git(self.main, 'config', 'user.name', 'Human Fixture')
        self.git(self.main, 'config', 'user.email', 'human@example.invalid')
        self.git(self.main, 'commit', '--allow-empty', '-qm', 'fixture')
        self.git(self.main, 'worktree', 'add', '-qb', 'linked', str(self.linked))
        self.private = self.common / 'worktrees/linked'

    def command(self, cwd, argv, *, input=None, success=True):
        output = subprocess.run([str(a) for a in argv], cwd=cwd, env=self.environment,
            input=input, text=True, capture_output=True, timeout=40)
        self.record(dict(kind='command', cwd=str(cwd), argv=[str(a) for a in argv],
                         stdin=input, exit=output.returncode, stdout=output.stdout, stderr=output.stderr))
        if success:
            self.assertEqual(0, output.returncode, output.stderr)
        return output

    def git(self, cwd, *args):
        return self.command(cwd, ['git', *args])

    def ti(self, cwd, *args, **kwargs):
        return self.command(cwd, [self.native, *args], **kwargs)

    def new(self, cwd, title):
        return self.ti(cwd, 'new', '--title', title, '--id-only').stdout.strip()

    def launch(self, cwd):
        from tic_broker import TicBrokerLaunch
        launch = TicBrokerLaunch(self.build, workspace=cwd, common_dir=self.common,
            user_name='Broker Fixture', user_email='broker@example.invalid', namespace='tickets')
        self.addCleanup(launch.stop)
        launch.start()
        self.record(dict(kind='broker-ready', workspace=str(cwd), common_dir=str(self.common),
                         address=launch.address, pid=launch.process.pid))
        return launch

    def exchange(self, launch, argv):
        import socket
        data = self.json.dumps(dict(token=launch.token, request=dict(version=2, command='tic',
                                    argv=argv, stdin=''))).encode()
        host, port = launch.address.rsplit(':', 1)
        with socket.create_connection((host, int(port)), timeout=40) as connection:
            connection.sendall(len(data).to_bytes(4, 'big') + data)
            received = bytearray()
            while chunk := connection.recv(65536):
                received.extend(chunk)
        self.assertGreaterEqual(len(received), 4)
        self.assertEqual(len(received) - 4, int.from_bytes(received[:4], 'big'))
        response = self.json.loads(received[4:])
        self.record(dict(kind='broker-response', argv=argv, response=response))
        return response

    def no_private_store(self):
        for suffix in ('', '-wal', '-shm'):
            self.assertFalse((self.private / ('git-meta.sqlite' + suffix)).exists())

    def test_fresh_creation_reopen_sidecars_and_native_contention(self):
        import sqlite3
        import time
        self.assertFalse((self.common / 'git-meta.sqlite').exists())
        broker = self.launch(self.linked)
        # Readiness is not a store open.
        self.assertFalse((self.common / 'git-meta.sqlite').exists())
        first = self.new(self.linked, 'created from linked native')
        database = self.common / 'git-meta.sqlite'
        identity = (database.stat().st_dev, database.stat().st_ino)
        self.assertIn('created from linked native', self.ti(self.main, 'show', first, '--json').stdout)
        holder = sqlite3.connect(database, timeout=0)
        self.addCleanup(holder.close)
        self.assertEqual('wal', holder.execute('pragma journal_mode').fetchone()[0])
        holder.execute('BEGIN IMMEDIATE')
        identities = {}
        for suffix in ('', '-wal', '-shm'):
            file = self.common / ('git-meta.sqlite' + suffix)
            identities[file.name] = [file.stat().st_dev, file.stat().st_ino]
        self.record(dict(kind='live-shared-files', identities=identities))
        start = time.monotonic()
        contended = self.ti(self.linked, 'new', '--title', 'native contention attempt', '--id-only', success=False)
        self.assertNotEqual(0, contended.returncode)
        self.assertRegex(contended.stderr.lower(), 'locked|busy')
        self.record(dict(kind='native-contention', elapsed=time.monotonic() - start))
        holder.rollback()
        second = self.exchange(broker, ['new', '--title', 'broker after lock release', '--id-only'])
        self.assertEqual(0, second['exit'], second)
        for cwd in (self.main, self.linked):
            self.assertIn('broker after lock release', self.ti(cwd, 'show', second['stdout'].strip(), '--json').stdout)
        self.assertEqual(identity, (database.stat().st_dev, database.stat().st_ino))
        self.no_private_store()

    def test_concurrent_human_and_broker_writes_are_visible_without_replay(self):
        from concurrent.futures import ThreadPoolExecutor
        self.new(self.main, 'initial shared database')
        one, two = self.launch(self.main), self.launch(self.linked)
        self.assertNotEqual(one.address, two.address)
        titles = ['concurrent-%02d' % n for n in range(18)]
        def write(pair):
            index, title = pair
            if index % 3 == 0:
                output = self.ti(self.linked, 'new', '--title', title, '--id-only', success=False)
                return title, output.returncode, output.stdout, output.stderr
            response = self.exchange(one if index % 3 == 1 else two,
                                     ['new', '--title', title, '--id-only'])
            return title, response['exit'], response['stdout'], response['stderr']
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(write, enumerate(titles)))
        # No command-level retry or application writer lock in the test.
        self.record(dict(kind='concurrent-results', results=results))
        # Native SQLite contention is permitted, not a broker failure or an
        # excuse to replay an outcome-unknown mutation. This sampled run still
        # requires successful independent human and broker writes.
        self.assertTrue(any(result[1] == 0 for result in results[::3]), results)
        self.assertTrue(any(result[1] == 0 for index, result in enumerate(results) if index % 3), results)
        for result in results:
            if result[1] != 0:
                self.assertRegex(result[3].lower(), 'locked|busy')
        main = self.ti(self.main, 'list', '--all', '--json').stdout
        linked = self.ti(self.linked, 'list', '--all', '--json').stdout
        self.assertEqual(self.json.loads(main), self.json.loads(linked))
        for title, status, ticket, _ in results:
            if status == 0:
                self.assertIn(title, main)
                self.assertIn(title, self.ti(self.main, 'show', ticket.strip(), '--json').stdout)
        self.no_private_store()

    def test_history_human_ui_relative_files_review_keep_invocation_context(self):
        first = self.new(self.main, 'main selection')
        subdir = self.linked / 'nested'
        subdir.mkdir()
        (subdir / 'draft.txt').write_text('Linked relative file\n\nOnly in linked nested cwd.\n')
        second = self.ti(subdir, 'new', '-F', 'draft.txt', '--id-only').stdout.strip()
        self.assertIn('Only in linked nested cwd.', self.ti(self.main, 'show', second, '--json').stdout)
        self.ti(self.main, 'checkout', first)
        absent = self.ti(self.linked, 'show', '--json', success=False)
        self.assertNotEqual(0, absent.returncode)
        self.assertIn('none checked out', absent.stderr)
        self.ti(self.linked, 'checkout', second)
        self.ti(self.linked, 'comment', 'linked current ticket comment')
        self.assertIn('main selection', self.ti(self.main, 'show', '--json').stdout)
        history_main = self.ti(self.main, 'history', '-t', second, '--json').stdout
        self.assertEqual(history_main, self.ti(self.linked, 'history', '-t', second, '--json').stdout)
        self.assertIn('(comment added)', history_main)
        review = self.ti(subdir, 'review', 'new', '--ticket', second, '--title', 'Default linked branch')
        self.assertIn('Created review linked@', review.stdout)
        self.assertIn('Default linked branch', self.ti(self.main, 'review', 'list', '--json').stdout)
        self.ti(self.main, 'list', '--tag', 'main-filter', '--json')
        self.ti(self.linked, 'list', '--tag', 'linked-filter', '--json')
        before = self.ui.read_bytes()
        state = self.json.loads(before)
        self.assertEqual(2, len(state['current']))
        self.assertEqual(2, len(state['last_filters']))
        self.assertIn('main-filter', str(state['last_filters']))
        self.assertIn('linked-filter', str(state['last_filters']))
        broker = self.launch(self.linked)
        response = self.exchange(broker, ['list', '--tag', 'broker-filter', '--json'])
        self.assertEqual(0, response['exit'])
        self.assertEqual(before, self.ui.read_bytes(), 'broker must not change human UI state')
        self.no_private_store()

    def test_explicit_setup_sync_report_common_context(self):
        remote = self.root / 'remote.git'
        self.git(self.root, 'init', '--bare', '-q', str(remote))
        self.git(self.main, 'config', 'extensions.worktreeConfig', 'true')
        self.git(self.main, 'config', 'meta.namespace', 'shared')
        self.git(self.linked, 'config', '--worktree', 'meta.namespace', 'private')
        (self.linked / '.git-meta').write_text('url: ' + str(remote) + '\n')
        self.ti(self.linked, 'init')
        self.ti(self.linked, 'setup')
        self.assertIn('Git Metadata Repository', self.git(remote, 'show', 'refs/shared/main:README.md').stdout)
        self.new(self.linked, 'published shared context')
        for command in ('push', 'sync'):
            output = self.ti(self.linked, command)
            self.assertIn('Remote: meta', output.stdout)
            self.assertIn('Ref: refs/shared/main', output.stdout)
        self.git(remote, 'show-ref', '--verify', 'refs/shared/main')
        self.assertIn('already configured', self.ti(self.main, 'setup').stdout)
        self.no_private_store()

    def test_real_independent_legacy_database_refused_preserving_all_bytes(self):
        import hashlib
        import shutil
        import sqlite3
        # A real native-created store containing a ticket, relocated only inside
        # this offline test fixture to model an independent historical store.
        # The product must refuse it; the test performs no product migration.
        seed = self.root / 'legacy-seed'
        self.git(self.root, 'init', '-qb', 'main', str(seed))
        self.git(seed, 'config', 'user.name', 'Independent Fixture')
        self.git(seed, 'config', 'user.email', 'independent@example.invalid')
        self.new(seed, 'do not lose independent worktree ticket')
        legacy = self.private / 'git-meta.sqlite'
        shutil.copyfile(seed / '.git/git-meta.sqlite', legacy)
        holder = sqlite3.connect(legacy)
        self.addCleanup(holder.close)
        self.assertEqual('wal', holder.execute('pragma journal_mode').fetchone()[0])
        holder.execute('select name from sqlite_master').fetchall()
        files = [self.private / ('git-meta.sqlite' + suffix) for suffix in ('', '-wal', '-shm')]
        snapshot = lambda: {str(path): dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size=path.stat().st_size, inode=path.stat().st_ino, mtime_ns=path.stat().st_mtime_ns)
            for path in files}
        before = snapshot()
        for cwd in (self.main, self.linked):
            for argv in (('list', '--json'), ('init',)):
                output = self.ti(cwd, *argv, success=False)
                self.assertNotEqual(0, output.returncode)
                self.assertIn('legacy worktree-local', output.stderr)
            # Inspection/startup reject without opening SQLite.
            output = self.command(cwd, [self.build.broker_executable, 'inspect-context',
                '--workspace', cwd, '--common-dir', self.common], success=False)
            self.assertNotEqual(0, output.returncode)
            from trusted_services import LifecycleError
            with self.assertRaises(LifecycleError):
                self.launch(cwd)
        self.assertEqual(before, snapshot())
        self.record(dict(kind='legacy-before-after-identical', files=before))
        self.assertFalse((self.common / 'git-meta.sqlite').exists())
