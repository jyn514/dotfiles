"""Preserve real JJ work while collecting ignored files, with volume exclusion."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from work_cleanup_guest import clean_volume
from work_storage import volume_admission, idle_workspaces, cleanup_work_storage
from workspace_layout import discover_workspace, ensure_request_lock, workspace_work_volume


class ResetCleanupTest(unittest.TestCase):
    def test_reset_runs_maintenance_after_teardown_and_retains_failed_recovery(self):
        spec = importlib.util.spec_from_file_location(
            'work_cleanup_reset', Path(__file__).resolve().parents[1] / 'sandbox-proxies.py')
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'session.json'
                path.write_text(json.dumps({'version': 4, 'services': {}}))
                events = []
                def maintenance(metadata, state):
                    events.append('maintenance')
                    if fails:
                        raise ValueError('snapshot failed')
                with patch.object(helpers, 'recoverable_session_state', return_value={'proxies': []}), \
                        patch.object(helpers, 'stop_state', side_effect=lambda state: events.append('teardown')), \
                        patch.object(helpers, 'cleanup_session_work_storage', side_effect=maintenance):
                    if fails:
                        with self.assertRaisesRegex(ValueError, 'snapshot failed'):
                            helpers.reset_session(Path(directory))
                    else:
                        helpers.reset_session(Path(directory))
                self.assertEqual(events, ['teardown', 'maintenance'])
                self.assertEqual(path.exists(), fails)


class WorkCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.jj = os.environ.get("DOTFILES_TEST_JJ_REAL", "jj")
        self.environment = patch.dict(os.environ, {"HOME": str(self.directory / "home"), "JJ_REAL": self.jj})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.root = self.directory / "main"
        self.run_jj("git", "init", "--colocate", str(self.root), cwd=self.directory)
        self.run_jj("config", "set", "--repo", "user.name", "Fixture")
        self.run_jj("config", "set", "--repo", "user.email", "fixture@example.invalid")
        self.volume = self.root / "work"
        self.volume.mkdir()
        self.other = self.volume / "other"
        self.run_jj("workspace", "add", "--no-colocate", str(self.other))
        self.layout = discover_workspace(self.root, Path('/home/codex/src/project'), self.directory / "home")
        ensure_request_lock(self.layout)
        self.authority = {**self.layout.proxy_authority(), "volume": str(self.volume),
                          "root": str(self.root), "jj_repo": str(self.root / '.jj/repo')}

    def run_jj(self, *arguments, cwd=None):
        return subprocess.run([self.jj, *arguments], cwd=cwd or self.root,
                              check=True, capture_output=True, text=True).stdout

    def ignored_output(self, root=None):
        root = root or self.other
        (root / ".gitignore").write_text("*.tmp\ncache/\n")
        (root / "out.tmp").write_text("discard")
        (root / "tracked").write_text("preserve")
        return root / "out.tmp"

    def test_snapshots_tracked_work_and_preserves_authorship_and_registrations(self):
        ignored = self.ignored_output()
        self.run_jj("file", "list", cwd=self.other)
        before = self.run_jj("log", "--no-graph", "-r", "@", "-T", "json(author)", cwd=self.other)
        (self.other / "tracked").write_text("pending edit")
        (self.other / "new").write_text("pending addition")
        self.assertEqual(clean_volume(self.authority), 1)
        self.assertFalse(ignored.exists())
        self.assertEqual((self.other / "tracked").read_text(), "pending edit")
        self.assertEqual(self.run_jj("file", "show", "--ignore-working-copy", "tracked", cwd=self.other), "pending edit")
        self.assertEqual(self.run_jj("file", "show", "--ignore-working-copy", "new", cwd=self.other), "pending addition")
        self.assertEqual(self.run_jj("log", "--no-graph", "-r", "@", "-T", "json(author)", cwd=self.other), before)
        self.assertTrue((self.other / ".jj").is_dir())
        self.assertIn('other', self.run_jj("workspace", "list", "--ignore-working-copy"))

    def test_tracked_ignored_file_and_unclassified_volume_files_survive(self):
        tracked = self.other / "keep.tmp"
        tracked.write_text("tracked before ignored")
        self.run_jj("file", "list", cwd=self.other)
        ignored = self.ignored_output()
        orphan = self.volume / "unclassified.tmp"
        orphan.write_text("keep")
        clean_volume(self.authority)
        self.assertTrue(tracked.exists())
        self.assertTrue(orphan.exists())
        self.assertFalse(ignored.exists())

    def test_deleted_tracked_file_stays_deleted_and_conflicted_file_survives(self):
        ignored = self.ignored_output()
        (self.other / 'deleted').write_text('old')
        self.run_jj('new', '-m', 'base', cwd=self.other)
        (self.other / 'tracked').write_text('left')
        left = self.run_jj('log', '--no-graph', '-r', '@', '-T', 'commit_id', cwd=self.other)
        self.run_jj('new', '@-', '-m', 'right', cwd=self.other)
        (self.other / 'tracked').write_text('right')
        self.run_jj('new', '@', left, '-m', 'merge', cwd=self.other)
        # The merge has different edits to the same tracked file.
        before = (self.other / 'tracked').read_bytes()
        self.assertIn(b'<<<<<<<', before)
        (self.other / 'deleted').unlink()
        clean_volume(self.authority)
        self.assertEqual((self.other / 'tracked').read_bytes(), before)
        self.assertFalse((self.other / 'deleted').exists())
        self.assertNotIn('deleted', self.run_jj('file', 'list', '--ignore-working-copy', cwd=self.other))
        self.assertFalse(ignored.exists())

    def test_ignored_path_with_newline_and_global_ignore_rules(self):
        self.ignored_output()
        global_ignore = self.directory / 'ignore'
        global_ignore.write_text('*.global\n')
        global_config = self.directory / 'gitconfig'
        global_config.write_text('[core]\nexcludesFile = ' + str(global_ignore) + '\n')
        weird = self.other / 'with\nnewline.tmp'
        weird.write_text('ignored')
        global_file = self.other / 'out.global'
        global_file.write_text('ignored globally')
        with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(global_config)}):
            clean_volume(self.authority)
        self.assertFalse(weird.exists())
        self.assertFalse(global_file.exists())

    def test_nested_workspace_and_external_symlink_targets_survive(self):
        self.ignored_output()
        nested = self.other / "cache/nested"
        nested.parent.mkdir()
        self.run_jj("workspace", "add", "--no-colocate", str(nested))
        self.ignored_output(nested)
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "out.tmp").write_text("outside")
        (self.other / "link.tmp").symlink_to(outside, target_is_directory=True)
        clean_volume(self.authority)
        self.assertEqual((outside / "out.tmp").read_text(), "outside")
        self.assertTrue((nested / "tracked").exists())
        self.assertTrue((nested / ".jj").exists())
        self.assertFalse((nested / "out.tmp").exists())
        self.assertFalse((self.other / "link.tmp").is_symlink())

    def test_failed_later_snapshot_preserves_all_candidates(self):
        ignored = self.ignored_output()
        other = self.volume / "z-later"
        self.run_jj("workspace", "add", "--no-colocate", str(other))
        self.ignored_output(other)
        import work_cleanup_guest
        real = work_cleanup_guest.native_jj
        def fail(root, *args):
            if root == other and args[:2] == ("file", "list"):
                raise ValueError("snapshot failed")
            return real(root, *args)
        with patch.object(work_cleanup_guest, "native_jj", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "snapshot failed"):
                clean_volume(self.authority)
        self.assertTrue(ignored.exists())

    def test_nested_mount_is_not_walked_even_on_same_device(self):
        ignored = self.ignored_output()
        cache = self.other / "cache"
        cache.mkdir()
        (cache / "keep.tmp").write_text("mounted")
        with patch("work_cleanup_guest.mountpoints", return_value={self.volume, cache}):
            clean_volume(self.authority)
        self.assertFalse(ignored.exists())
        self.assertTrue((cache / "keep.tmp").exists())

    def test_volume_lock_excludes_admission_until_maintenance_finishes(self):
        entered, released = threading.Event(), threading.Event()
        def consumer():
            entered.set()
            with volume_admission([self.layout]):
                released.set()
        with volume_admission([self.layout]):
            worker = threading.Thread(target=consumer)
            worker.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(released.wait(0.1))
        worker.join(2)
        self.assertTrue(released.is_set())

    def test_old_consumer_mounts_prevent_maintenance_without_new_protocol(self):
        _, owner = workspace_work_volume(self.layout)
        class Runtime:
            def resource_owner_label(self, kind):
                return "owner"
            def run(self, args, **kwargs):
                return SimpleNamespace(stdout=json.dumps([{"Labels": {"owner": owner}}])
                                       if args[0] == "volume" else "old-container\n")
        self.assertEqual(idle_workspaces(Runtime(), [self.layout]), [])
        cleanup_work_storage(Runtime(), [self.layout], "unused", lambda staging: [], None)

    def test_wrong_volume_owner_prevents_maintenance(self):
        runtime = SimpleNamespace(
            resource_owner_label=lambda kind: 'owner',
            run=lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([{'Labels': {'owner': 'other'}}])))
        with self.assertRaisesRegex(ValueError, 'ownership changed'):
            cleanup_work_storage(runtime, [self.layout], 'unused', lambda staging: [], None)


if __name__ == "__main__":
    unittest.main()
