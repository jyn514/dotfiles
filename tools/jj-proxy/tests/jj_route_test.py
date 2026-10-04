#!/usr/bin/env python3
"""Consumer-level routing regressions, with real JJ metadata and mount records.

The mount records describe Linux mountinfo semantics; they do not claim to prove
real container mount protection. Tests never modify the selected host checkout.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROUTER = Path(__file__).resolve().parents[1] / 'route.py'
SPEC = importlib.util.spec_from_file_location('jj_route', ROUTER)
router = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = router
SPEC.loader.exec_module(router)
REAL_JJ = os.environ.get('JJ_ROUTE_TEST_JJ', '/opt/agent-tools/libexec/jj')


def mount(id, parent, point, root='/', device='0:1', fs='overlay', source='overlay'):
    def escape(value):
        return str(value).replace('\\', r'\134').replace(' ', r'\040').replace('\t', r'\011').replace('\n', r'\012')
    return f'{id} {parent} {device} {escape(root)} {escape(point)} rw - {fs} {escape(source)} rw\n'


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='jj-route-')
        cls.root = Path(cls.temp.name)
        cls.global_config = cls.root / 'config.toml'
        cls.global_config.write_text('[aliases]\ninit=["git","init"]\nclone=["git","clone"]\nc=["commit"]\n')
        cls.env = {'HOME': str(cls.root), 'JJ_CONFIG': str(cls.global_config)}
        cls.fixture = cls.root / 'fixture'
        if Path(REAL_JJ).is_file():
            subprocess.run([REAL_JJ, 'git', 'init', '--no-colocate', str(cls.fixture)],
                           env=cls.env, cwd=cls.root, check=True, capture_output=True)
        else:
            # Shapes proven by the real-JJ test below; no executable is needed
            # for the ordinary routing/mount/parser regressions.
            for path in ('working_copy', 'repo/store/git', 'repo/op_store', 'repo/op_heads'):
                (cls.fixture / '.jj' / path).mkdir(parents=True, exist_ok=True)
            (cls.fixture / '.jj/repo/store/git_target').write_text('git')
            (cls.fixture / '.jj/repo/store/type').write_text('git')
            (cls.fixture / '.jj/repo/store/git/HEAD').write_text('ref: refs/heads/main\n')
            (cls.fixture / '.jj/repo/store/git/objects').mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(dir=self.root))
        self.local = self.repo('local')
        self.host = self.repo('host')
        self.config = self.case / 'global.toml'
        self.config.write_text(self.global_config.read_text())
        self.env = dict(type(self).env, JJ_CONFIG=str(self.config),
                        SANDBOX_PROXY_DIR='/run/proxy', JJ_PROXY_REPO=str(self.host))
        self.mounts = mount(1, 0, '/') + mount(2, 1, self.host, '/host/project', '0:35', 'virtiofs', 'host')

    def repo(self, name):
        path = self.case / name
        shutil.copytree(self.fixture, path)
        return path

    def decision(self, args, cwd=None, mounts=None, env=None):
        return router.route(args, cwd=cwd or self.local, env=self.env if env is None else env,
                            mountinfo=self.mounts if mounts is None else mounts)

    def assertDecision(self, args, backend='native', workspace=None, destination=None,
                       command=None, hooks=True, **kwargs):
        result = self.decision(args, **kwargs)
        self.assertEqual(result, {'backend': backend,
                                 'workspace': str(workspace or self.local) if workspace is not False else None,
                                 'destination': str(destination) if destination else None,
                                 'command': command or args[:1], 'hooks': hooks})

    def test_local_and_host_workspaces_with_same_proxy_environment(self):
        self.assertDecision(['commit'])
        self.assertDecision(['commit'], cwd=self.host, backend='proxy', workspace=self.host)
        child = self.local / 'nested'
        child.mkdir()
        self.assertDecision(['split'], cwd=child, command=['split'])

    def test_selectors_target_workspace_not_cwd_or_message(self):
        for args in (['-R', str(self.local), 'commit'], ['-R' + str(self.local), 'commit'],
                     ['--repository', str(self.local), 'commit'],
                     ['--repository=' + str(self.local), 'commit'],
                     ['--quiet', '--config', 'x="--repository=/bad"', 'commit', '-R', str(self.local)]):
            with self.subTest(args=args):
                self.assertDecision(args, cwd=self.host, command=['commit'])
        self.assertDecision(['commit', '-m', '--repository=/bad'], command=['commit'])
        self.assertDecision(['commit', '-m--repository=/bad'], command=['commit'])
        self.assertDecision(['commit', '--', '-R', str(self.host)], command=['commit'])
        for args in (['commit', '-R'], ['-R', '/nonexistent', 'commit'],
                     ['-R', str(self.local), '-R', str(self.host), 'commit']):
            with self.subTest(args=args), self.assertRaises(router.RouteError):
                self.decision(args)

    def test_boolean_editor_does_not_swallow_selectors_or_hook_modes(self):
        for command in ('commit', 'describe', 'split', 'squash'):
            with self.subTest(command=command):
                self.assertDecision([command, '--editor', '-R', str(self.local), '-m', 'msg'],
                                    cwd=self.host, command=[command])
                self.assertDecision([command, '--editor', '--ignore-working-copy', '-m', 'msg'],
                                    command=[command], hooks=False)
        self.assertDecision(['rebase', '-s', '--ignore-working-copy'], command=['rebase'])
        self.assertDecision(['log', '-n', '2', '-R', str(self.local)], cwd=self.host, command=['log'])
        self.assertDecision(['log', '-sR' + str(self.local)], cwd=self.host, command=['log'])

    def test_audited_boolean_command_prefixes_preserve_selectors_and_no_wc(self):
        # Consumer examples from the installed-help audit, not the parser's
        # implementation table: each prefix must actually be reachable. In
        # particular, Gerrit upload is parsed as data; no upload is executed.
        examples = (
            ('diff', ('-b', '-s')),
            ('interdiff', ('-b', '-s')),
            ('show', ('-b', '-s')),
            ('evolog', ('-s',)),
            ('evolution-log', ('-s',)),
            ('log', ('-s',)),
            ('next', ('-n',)),
            ('prev', ('-n',)),
            ('gerrit upload', ('-n',)),
            ('bookmark list', ('-t',)),
            ('operation diff', ('-s',)),
            ('operation log', ('-d', '-s')),
            ('operation show', ('-s',)),
            ('op diff', ('-s',)),
            ('op log', ('-d', '-s')),
            ('op show', ('-s',)),
        )
        for prefix, options in examples:
            command = prefix.split()
            for option in options:
                with self.subTest(prefix=prefix, option=option, mode='selector'):
                    self.assertDecision(command + [option, '-R', str(self.local)],
                                        cwd=self.host, command=command)
                with self.subTest(prefix=prefix, option=option, mode='no-working-copy'):
                    self.assertDecision(command + [option, '--ignore-working-copy'],
                                        command=command, hooks=False)

    @unittest.skipUnless(Path(REAL_JJ).is_file(), 'installed native JJ required')
    def test_real_native_boolean_editor_selects_target_and_accepts_no_wc(self):
        env = dict(self.env, EDITOR='true', VISUAL='true', PATH='/usr/bin:/bin')
        heads = self.local / '.jj/repo/op_heads/heads'
        before = {p.name: p.read_bytes() for p in heads.iterdir() if p.is_file()}
        args = ['commit', '--editor', '-R', str(self.host), '-m', 'editor-selected-target']
        result = self.decision(args, cwd=self.local)
        self.assertEqual(result['workspace'], str(self.host))
        self.assertTrue(result['hooks'])
        subprocess.run([REAL_JJ] + args, cwd=self.local, env=env, check=True, capture_output=True)
        after = {p.name: p.read_bytes() for p in heads.iterdir() if p.is_file()}
        self.assertEqual(before, after, 'native selected commit modified the enclosing workspace')
        description = subprocess.run([REAL_JJ, '-R', str(self.host), '--ignore-working-copy',
                                      'log', '-r', '@-', '--no-graph', '-T', 'description'],
                                     cwd=self.case, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(description.stdout.strip(), 'editor-selected-target')
        args = ['commit', '--editor', '--ignore-working-copy', '-m', 'no-working-copy']
        self.assertFalse(self.decision(args)['hooks'])
        subprocess.run([REAL_JJ] + args, cwd=self.local, env=env, check=True, capture_output=True)

    def test_hook_modes_and_aliases(self):
        for mode in (['--ignore-working-copy'], ['--at-op', '@-'], ['--at-operation=@'],
                     ['-@', '@'], ['-@@-'], ['--no-integrate-operation']):
            with self.subTest(mode=mode):
                self.assertDecision(mode + ['c'], command=['commit'], hooks=False)
        for args, command in ((['--help'], ['log']), (['--version'], ['log']),
                              (['help', 'commit'], ['help']), (['version'], ['version']),
                              (['c', '--help'], ['commit'])):
            with self.subTest(args=args):
                self.assertDecision(args, command=command, hooks=False)
        self.assertDecision(['--color', 'never', '--no-pager', 'c'], command=['commit'])
        self.assertDecision(['commit', '-m', '--ignore-working-copy'], command=['commit'])

    def test_bootstrap_ignores_protected_enclosing_workspace(self):
        destination = self.case / 'new'
        for args in (['git', 'init', str(destination)], ['init', str(destination)],
                     ['git', 'clone', str(self.host), str(destination)],
                     ['clone', str(self.host), str(destination)]):
            with self.subTest(args=args):
                self.assertDecision(args, cwd=self.host, workspace=False, destination=destination,
                                    command=['git', 'clone' if 'clone' in args else 'init'])
        self.assertFalse(destination.exists())
        self.assertDecision(['init'], cwd=self.local, workspace=False, destination=self.local,
                            command=['git', 'init'])
        self.assertDecision(['clone', 'https://example.test/team/foo.git'], cwd=self.local,
                            workspace=False, destination=self.local / 'foo', command=['git', 'clone'])
        self.assertDecision(['clone', 'git@example.test:team/foo.git/'], cwd=self.local,
                            workspace=False, destination=self.local / 'foo.git', command=['git', 'clone'])
        self.assertDecision(['git', 'init', '--', '-R'], cwd=self.local, workspace=False,
                            destination=self.local / '-R', command=['git', 'init'])

    def test_authoritative_alias_change_is_not_a_duplicate_map(self):
        self.config.write_text('[aliases]\ninit=["git","clone","https://example.test/base.git"]\n')
        destination = self.case / 'cloned'
        self.assertDecision(['init', str(destination)], cwd=self.host, workspace=False,
                            destination=destination, command=['git', 'clone'])
        self.config.write_text('[aliases]\ninit=["commit"]\n')
        self.assertDecision(['init'], cwd=self.host, workspace=self.host, backend='proxy', command=['commit'])
        # Opaque aliases and cycles are left to JJ, not executed by the helper.
        self.config.write_text('[aliases]\ninit="!touch /tmp/router-must-not-execute"\na=["b"]\nb=["a"]\n')
        self.assertDecision(['init'], command=['init'], hooks=False)
        self.assertDecision(['a'], command=['a'], hooks=False)

    def test_default_global_config_and_jj_config_authority(self):
        home = self.case / 'home'
        config = home / '.config/jj/config.toml'
        config.parent.mkdir(parents=True)
        config.write_text('[aliases]\ni=["git","init"]\n')
        env = dict(self.env, HOME=str(home))
        del env['JJ_CONFIG']
        destination = self.case / 'default'
        self.assertDecision(['i', str(destination)], env=env, workspace=False,
                            destination=destination, command=['git', 'init'])
        env['JJ_CONFIG'] = ''
        self.assertDecision(['i', str(destination)], env=env, command=['i'])
        config.write_text('not valid TOML {{{')
        del env['JJ_CONFIG']
        self.assertDecision(['commit'], env=env, hooks=False)

    def test_metadata_symlinks_linked_workspaces_and_internal_git(self):
        shutil.rmtree(self.local / '.jj/repo')
        (self.local / '.jj/repo').write_text(os.path.relpath(self.host / '.jj/repo', self.local / '.jj'))
        self.assertDecision(['commit'], backend='proxy')
        (self.local / '.jj/repo').unlink()
        (self.local / '.jj/repo').symlink_to(self.host / '.jj/repo', target_is_directory=True)
        self.assertDecision(['split'], backend='proxy', command=['split'])
        linked = self.case / 'workspace-link'
        linked.symlink_to(self.local, target_is_directory=True)
        self.assertDecision(['commit'], cwd=linked, backend='proxy')
        independent = self.repo('independent')
        self.assertDecision(['commit'], cwd=independent, workspace=independent)
        (independent / '.jj/repo/store/git_target').write_text(str(self.host / '.jj/repo/store/git'))
        self.assertDecision(['commit'], cwd=independent, workspace=independent, backend='proxy')

    def test_supported_local_schema_ignores_unused_host_git_target(self):
        # This exercises the helper's accepted local schema, not a claim that
        # the installed native CLI can create/load this backend.
        store = self.local / '.jj/repo/store'
        (store / 'type').write_text('local')
        (store / 'git_target').write_bytes(os.fsencode(self.host / '.jj/repo/store/git'))
        self.assertDecision(['status'], command=['status'])
        (store / 'type').write_text('git')
        self.assertDecision(['status'], command=['status'], backend='proxy')

    def test_non_colocated_workspace_ignores_unrelated_host_git(self):
        # The fixture is initialized with --no-colocate: only git_target owns
        # JJ's effective backing. A coincidental .git must not force the proxy.
        host_git = self.host / '.jj/repo/store/git'
        (self.local / '.git').symlink_to(host_git, target_is_directory=True)
        self.assertDecision(['status'], command=['status'])
        # A genuine JJ backing reference still follows the same host identity.
        (self.local / '.jj/repo/store/git_target').write_bytes(os.fsencode(host_git))
        self.assertDecision(['status'], command=['status'], backend='proxy')

    @unittest.skipUnless(Path(REAL_JJ).is_file(), 'installed native JJ required')
    def test_real_native_non_colocated_status_ignores_unrelated_host_git(self):
        (self.local / '.git').symlink_to(self.host / '.jj/repo/store/git', target_is_directory=True)
        result = self.decision(['status'])
        self.assertEqual(result['backend'], 'native')
        self.assertTrue(result['hooks'])
        status = subprocess.run([REAL_JJ, 'status'], cwd=self.local, env=self.env,
                                check=True, capture_output=True, text=True)
        self.assertIn('Working copy  (@)', status.stdout)
        # git_target names the internal bare directory as-is; its unrelated
        # .git child must not replace the effective backing either.
        (self.local / '.jj/repo/store/git/.git').symlink_to(
            self.host / '.jj/repo/store/git', target_is_directory=True)
        self.assertDecision(['status'], command=['status'])
        subprocess.run([REAL_JJ, 'status'], cwd=self.local, env=self.env,
                       check=True, capture_output=True)

    def test_bootstrap_uses_only_selected_colocation_or_explicit_git_backing(self):
        destination = self.case / 'bootstrap-unused-git'
        destination.mkdir()
        (destination / '.git').symlink_to(self.host / '.jj/repo/store/git', target_is_directory=True)
        self.assertDecision(['git', 'init', str(destination)], backend='proxy',
                            workspace=False, destination=destination, command=['git', 'init'])
        self.assertDecision(['git', 'init', '--no-colocate', str(destination)],
                            workspace=False, destination=destination, command=['git', 'init'])
        self.assertDecision(['git', 'init', '--git-repo', str(self.local / '.jj/repo/store/git'), str(destination)],
                            workspace=False, destination=destination, command=['git', 'init'])
        self.config.write_text('[git]\ncolocate=false\n')
        self.assertDecision(['git', 'init', str(destination)],
                            workspace=False, destination=destination, command=['git', 'init'])
        self.assertDecision(['git', 'init', '--colocate', str(destination)], backend='proxy',
                            workspace=False, destination=destination, command=['git', 'init'])
        # Discovery is still correct for explicit --git-repo worktree inputs.
        worktree = self.case / 'explicit-git-worktree'
        worktree.mkdir()
        (worktree / '.git').symlink_to(self.host / '.jj/repo/store/git', target_is_directory=True)
        self.assertDecision(['git', 'init', '--git-repo', str(worktree), str(self.case / 'shared')],
                            backend='proxy', workspace=False, destination=self.case / 'shared', command=['git', 'init'])

    @unittest.skipUnless(Path(REAL_JJ).is_file(), 'installed native JJ required')
    def test_real_native_bootstrap_explicit_backing_ignores_destination_git(self):
        destination = self.case / 'shared-native'
        destination.mkdir()
        (destination / '.git').symlink_to(self.host / '.jj/repo/store/git', target_is_directory=True)
        args = ['git', 'init', '--git-repo', str(self.local / '.jj/repo/store/git'), str(destination)]
        self.assertEqual(self.decision(args)['backend'], 'native')
        subprocess.run([REAL_JJ] + args, cwd=self.case, env=self.env, check=True, capture_output=True)
        self.assertEqual((destination / '.jj/repo/store/git_target').read_bytes(),
                         os.fsencode(self.local / '.jj/repo/store/git'))
        # --no-colocate does not use .git, but native refuses initialization
        # alongside an existing Git repo; preserve that native diagnostic.
        rejected = self.case / 'no-colocate-existing-git'
        rejected.mkdir()
        (rejected / '.git').symlink_to(self.host / '.jj/repo/store/git', target_is_directory=True)
        args = ['git', 'init', '--no-colocate', str(rejected)]
        self.assertEqual(self.decision(args)['backend'], 'native')
        proc = subprocess.run([REAL_JJ] + args, cwd=self.case, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('existing Git repo', proc.stderr)
        self.assertFalse((rejected / '.jj').exists())

    def test_gitfiles_common_dirs_and_explicit_bootstrap_backing(self):
        git = self.case / 'git-worktree'
        git.mkdir()
        (git / 'HEAD').write_text('ref: refs/heads/main\n')
        (git / 'commondir').write_text(os.path.relpath(self.host / '.jj/repo/store/git', git))
        gitfile = self.case / 'gitfile'
        gitfile.write_text('gitdir: ' + os.path.relpath(git, gitfile.parent))
        (self.local / '.jj/repo/store/git_target').write_text(str(gitfile))
        self.assertDecision(['commit'], backend='proxy')
        destination = self.case / 'new'
        self.assertDecision(['git', 'init', '--git-repo', str(gitfile), str(destination)],
                            workspace=False, destination=destination, command=['git', 'init'], backend='proxy')
        gitfile.write_text('not a gitfile')
        self.assertDecision(['commit'], hooks=False)

    def test_broken_unknown_metadata_skip_hooks_without_denying_native(self):
        (self.local / '.jj/repo/store/git_target').write_text('/does-not-exist')
        self.assertDecision(['commit'], hooks=False)
        shutil.rmtree(self.local / '.jj/repo')
        (self.local / '.jj/repo').write_text('')
        self.assertDecision(['commit'], hooks=False)
        empty = self.case / 'empty'
        empty.mkdir()
        self.assertDecision(['status'], cwd=empty, workspace=False, hooks=False, command=['status'])
        self.assertDecision(['commit'], cwd=self.host, workspace=self.host, backend='proxy')

    def test_alias_mount_compares_backing_region_not_only_device(self):
        alias = self.repo('alias with space')
        mounts = self.mounts + mount(3, 1, alias, '/host/project', '0:35', 'virtiofs', 'host')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts, backend='proxy')
        mounts = self.mounts + mount(3, 1, alias, '/guest-volume', '0:35', 'virtiofs', 'host')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts)
        # No known-host evidence: non-rootfs and unrecognized filesystems native.
        mounts = mount(1, 0, '/') + mount(3, 1, alias, '/', '8:8', 'btrfs', '/dev/guest')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts)

    def test_explicit_selected_role_on_root_mount_anchors_only_its_region(self):
        mounts = mount(1, 0, '/')
        self.assertDecision(['commit'], cwd=self.host, workspace=self.host,
                            mounts=mounts, backend='proxy')
        self.assertDecision(['commit'], mounts=mounts)
        private = self.repo('host/private-role')
        self.assertDecision(['commit'], cwd=private, workspace=private,
                            mounts=mounts, backend='proxy')
        for device, fs, source in (('0:99', 'tmpfs', 'tmpfs'), ('8:8', 'ext4', '/dev/guest')):
            with self.subTest(fs=fs):
                nested = mounts + mount(2, 1, private, '/', device, fs, source)
                self.assertDecision(['commit'], cwd=private, workspace=private, mounts=nested)
        # The same rootfs is not host evidence without an explicit selected role.
        env = dict(self.env)
        del env['JJ_PROXY_REPO']
        self.assertDecision(['commit'], cwd=self.host, workspace=self.host, mounts=mounts, env=env)

    def test_nested_mounts_and_hidden_stacked_descendants(self):
        private = self.repo('host/private')
        mounts = self.mounts + mount(3, 2, private, '/', '0:99', 'tmpfs', 'tmpfs')
        self.assertDecision(['commit'], cwd=private, workspace=private, mounts=mounts)
        # Old protected child mount hidden by a newer same-point guest mount.
        mounts += mount(4, 3, private / '.jj', '/host/project/.jj', '0:35', 'virtiofs', 'host')
        # Mount IDs may be recycled: the upper mount has a lower ID.
        mounts += mount(0, 3, private, '/', '8:2', 'ext4', '/dev/guest')
        self.assertDecision(['commit'], cwd=private, workspace=private, mounts=mounts)
        mounts += mount(6, 0, private / '.jj', '/host/project/.jj', '0:35', 'virtiofs', 'host')
        self.assertDecision(['commit'], cwd=private, workspace=private, mounts=mounts, backend='proxy')

    def test_protected_metadata_separate_backing_identity(self):
        mounts = self.mounts + mount(3, 2, self.host / '.jj', '/protected-jj', '8:4', 'ext4', '/dev/metadata')
        alias = self.repo('metadata-only')
        mounts += mount(4, 1, alias / '.jj', '/protected-jj', '8:4', 'ext4', '/dev/metadata')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts, backend='proxy')

    def test_source_view_and_private_source_view_submount(self):
        # Path /src is a namespace anchor, not an arbitrary fixture parameter.
        mounts = mount(1, 0, '/') + mount(2, 1, '/src', '/host/src', '0:35', 'virtiofs', 'host')
        alias = self.repo('source-alias')
        mounts += mount(3, 1, alias, '/host/src/other-project', '0:35', 'virtiofs', 'host')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts, backend='proxy')
        mounts += mount(4, 3, alias, '/guest', '8:9', 'ext4', '/dev/private')
        self.assertDecision(['commit'], cwd=alias, workspace=alias, mounts=mounts)

    def test_metadata_paths_preserve_whitespace_and_working_copy_backing(self):
        host = self.repo('host with trailing newline\n')
        mounts = mount(1, 0, '/') + mount(2, 1, host, '/host/newline', '0:35', 'virtiofs', 'host')
        env = dict(self.env, JJ_PROXY_REPO=str(host))
        shutil.rmtree(self.local / '.jj/repo')
        (self.local / '.jj/repo').write_bytes(os.fsencode(host / '.jj/repo'))
        self.assertDecision(['commit'], backend='proxy', env=env, mounts=mounts)
        other = self.repo('working-copy-only')
        shutil.rmtree(other / '.jj/working_copy')
        (other / '.jj/working_copy').symlink_to(host / '.jj/working_copy', target_is_directory=True)
        self.assertDecision(['commit'], cwd=other, workspace=other, backend='proxy', env=env, mounts=mounts)
        # Even a broken known-host metadata reference routes proxy, without hooks.
        (self.local / '.jj/repo').write_bytes(os.fsencode(host / '.jj/nonexistent'))
        self.assertDecision(['commit'], backend='proxy', hooks=False, env=env, mounts=mounts)

    def test_config_directory_authority_ignores_non_toml_and_orders_layers(self):
        config = self.case / 'config-directory'
        config.mkdir()
        (config / '10.toml').write_text('[aliases]\ni=["commit"]\n')
        (config / '20.toml').write_text('[aliases]\ni=["git","init"]\n')
        (config / 'ignore-me').write_text('invalid TOML {{{')
        env = dict(self.env, JJ_CONFIG=str(config))
        destination = self.case / 'layers'
        self.assertDecision(['i', str(destination)], env=env, workspace=False,
                            destination=destination, command=['git', 'init'])
        self.config.write_text('[ui]\ndefault-command=["c"]\n[aliases]\nc=["commit"]\n')
        self.assertDecision([], command=['commit'])
        self.assertDecision(['-qR' + str(self.local), 'c'], cwd=self.host, command=['commit'])

    def test_unknown_backend_or_git_directory_does_not_enable_hooks(self):
        (self.local / '.jj/repo/store/type').write_text('unknown-backend')
        self.assertDecision(['commit'], hooks=False)
        self.assertDecision(['git', 'init'], workspace=False, destination=self.local,
                            command=['git', 'init'], hooks=False)
        (self.local / '.jj/repo/store/type').write_text('git')
        (self.local / '.jj/repo/store/git/HEAD').unlink()
        self.assertDecision(['commit'], hooks=False)
        self.assertDecision(['commit', '-m'], command=['commit'], hooks=False)

    def test_no_known_host_evidence_does_not_deny_bootstrap_by_lexical_src(self):
        self.assertDecision(['git', 'init', '/src/not-host-backed'], mounts=mount(1, 0, '/'),
                            workspace=False, destination=Path('/src/not-host-backed'), command=['git', 'init'])
        # Routing parses aliases as data and never executes native probes.
        with patch.object(subprocess, 'run', side_effect=AssertionError('router probe')):
            self.assertDecision(['commit'])

    def test_non_sandbox_does_not_read_proc_or_require_mount_evidence(self):
        env = dict(self.env)
        del env['SANDBOX_PROXY_DIR']
        original = Path.read_text
        def read(path, *args, **kwargs):
            self.assertNotEqual(str(path), '/proc/self/mountinfo')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            self.assertDecision(['commit'], cwd=self.host, workspace=self.host, env=env)

    def test_cli_is_single_checked_object_and_errors_are_status125(self):
        env = dict(self.env)
        del env['SANDBOX_PROXY_DIR']
        proc = subprocess.run([sys.executable, str(ROUTER), '--', '-R', str(self.local), 'c'],
                              cwd=self.host, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        result = json.loads(proc.stdout)
        router.check_result(result)
        self.assertEqual(result['workspace'], str(self.local))
        self.assertEqual(result['command'], ['commit'])
        for args in ([], ['--', '-R']):
            proc = subprocess.run([sys.executable, str(ROUTER)] + args, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 125)
            self.assertEqual(proc.stdout, '')
            self.assertTrue(proc.stderr.startswith('jj route: '))

    @unittest.skipUnless(Path(REAL_JJ).is_file(), 'installed native JJ required')
    def test_real_clone_default_canonicalizes_source_before_destination(self):
        source = self.case / 'source-link.git'
        source.symlink_to(self.fixture / '.jj/repo/store/git', target_is_directory=True)
        for index, argument in enumerate((str(source), str(source) + '/', source.as_uri(), 'source-link.git')):
            cwd = self.case / str(index)
            cwd.mkdir()
            if not argument.startswith('/') and not argument.startswith('file:'):
                (cwd / 'source-link.git').symlink_to(source, target_is_directory=True)
            result = self.decision(['clone', argument], cwd=cwd)
            subprocess.run([REAL_JJ, 'clone', argument], cwd=cwd, env=self.env, check=True, capture_output=True)
            self.assertEqual(result['destination'], str(cwd / 'git'))
            self.assertTrue((Path(result['destination']) / '.jj/repo').exists())

    @unittest.skipUnless(Path(REAL_JJ).is_file(), 'installed native JJ required')
    def test_real_linked_workspace_git_target_and_global_alias_consumers(self):
        repo = self.case / 'actual'
        linked = self.case / 'actual-linked'
        subprocess.run([REAL_JJ, 'git', 'init', '--no-colocate', str(repo)],
                       env=self.env, cwd=self.case, check=True, capture_output=True)
        subprocess.run([REAL_JJ, '-R', str(repo), 'workspace', 'add', str(linked)],
                       env=self.env, cwd=self.case, check=True, capture_output=True)
        self.assertTrue((linked / '.jj/repo').is_file())
        mounts = mount(1, 0, '/') + mount(2, 1, repo, '/actual-host', '0:35', 'virtiofs', 'host')
        env = dict(self.env, JJ_PROXY_REPO=str(repo))
        self.assertDecision(['commit'], cwd=linked, workspace=linked, backend='proxy', env=env, mounts=mounts)
        for command in ('init', 'clone'):
            self.config.write_text('[aliases]\nbootstrap=["git","' + command + '"]\n')
            args = ['bootstrap', str(repo / '.jj/repo/store/git'), str(self.case / 'clone')] if command == 'clone' else ['bootstrap', str(self.case / 'init')]
            result = self.decision(args, cwd=self.host)
            subprocess.run([REAL_JJ] + args, cwd=self.host, env=self.env, check=True, capture_output=True)
            destination = Path(result['destination'])
            self.assertTrue((destination / '.jj/repo').exists())
            self.assertEqual(result['backend'], 'native')
            self.assertEqual(result['command'], ['git', command])


if __name__ == '__main__':
    unittest.main()
