"""Readable work roots do not depend on launch order or allocation state."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from work_storage import assign_work_roots
from workspace_layout import WorkspaceLayout, WorkspaceError, workspace_work_root, workspace_work_volume


def workspace(root):
    return WorkspaceLayout(Path(root), Path('/home/codex/src/project'),
                           Path(root) / '.git', Path(root) / '.git',
                           Path(root) / '.jj/repo', Path('/host/locks/project.lock'))


class WorkStorageNamesTest(unittest.TestCase):
    def assign(self, *items):
        return assign_work_roots(items)

    def test_names_are_identical_alone_reordered_or_in_a_later_launch(self):
        first = workspace('/host/team/dotfiles')
        second = workspace('/host/other/dotfiles')
        first_name = self.assign(first)[0].work_root
        second_name = self.assign(second)[0].work_root
        self.assertEqual(Path('/work/dotfiles-116383'), first_name)
        self.assertEqual(Path('/work/dotfiles-763218'), second_name)
        self.assertNotEqual(first_name, second_name)
        self.assertEqual([first_name, second_name], [item.work_root for item in self.assign(first, second)])
        self.assertEqual([second_name, first_name], [item.work_root for item in self.assign(second, first)])
        self.assertEqual(workspace_work_volume(first), workspace_work_volume(self.assign(first)[0]))

    def test_name_has_no_home_cache_or_registry_dependency(self):
        layout = workspace('/host/team/dotfiles')
        with mock.patch('pathlib.Path.home', side_effect=AssertionError('home lookup')), \
                mock.patch('pathlib.Path.open', side_effect=AssertionError('filesystem lookup')):
            first = self.assign(layout)
            self.assertEqual(first, self.assign(layout))

    def test_maximum_length_basename_keeps_complete_suffix_within_directory_limit(self):
        basename = 'x' * 255
        selected = self.assign(workspace('/one/' + basename), workspace('/two/' + basename))
        with tempfile.TemporaryDirectory() as temporary:
            for item in selected:
                self.assertEqual(255, len(item.work_root.name.encode()))
                self.assertRegex(item.work_root.name, r'^x+-[0-9]{6}$')
                (Path(temporary) / item.work_root.name).mkdir()
        self.assertNotEqual(selected[0].work_root, selected[1].work_root)

    def test_host_basename_not_projected_source_name_or_invocation_subdirectory(self):
        layout = replace(workspace('/external/my-repo'), guest_root=Path('/home/codex/src/repository'))
        selected = self.assign(layout)[0]
        self.assertRegex(str(selected.work_root), r'^/work/my-repo-[0-9]{6}$')
        self.assertEqual(selected.work_root, self.assign(
            replace(layout, guest_root=Path('/home/codex/src/moved')))[0].work_root)

    def test_mount_unsafe_basename_has_a_readable_single_component(self):
        for basename, expected in [('my project!one', 'my-project-one'), ('...', 'repository'),
                                   ('-flags', 'flags'), ('_hidden', '_hidden')]:
            with self.subTest(basename=basename):
                self.assertRegex(self.assign(workspace('/host/' + basename))[0].work_root.name,
                                 '^' + expected + r'-[0-9]{6}$')

    def test_concurrent_calculations_return_the_same_paths_as_sequential_launches(self):
        layouts = [workspace('/one/project'), workspace('/two/project'), workspace('/one/project')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            selected = list(pool.map(lambda layout: self.assign(layout)[0], layouts))
        self.assertEqual(selected, [self.assign(layout)[0] for layout in layouts])
        self.assertEqual(selected[0].work_root, selected[2].work_root)
        self.assertNotEqual(selected[0].work_root, selected[1].work_root)

    def test_a_short_suffix_collision_is_an_error_not_an_order_based_rename(self):
        first, second = workspace('/one/project'), workspace('/two/project')
        with mock.patch('work_storage.named_work_root', return_value=Path('/work/project-123456')):
            for order in ((first, second), (second, first)):
                with self.subTest(order=order), self.assertRaisesRegex(WorkspaceError, 'Work storage name collision'):
                    self.assign(*order)
            self.assertEqual([Path('/work/project-123456')] * 2,
                             [item.work_root for item in self.assign(first, first)])

    def test_old_session_records_keep_hash_or_previously_selected_mount(self):
        spec = importlib.util.spec_from_file_location(
            'work_name_proxies', Path(__file__).resolve().parents[1] / 'sandbox-proxies.py')
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        legacy = workspace('/host/dotfiles')
        allocated = replace(legacy, work_root=Path('/work/dotfiles-2'))
        deterministic = self.assign(legacy)[0]
        volume, _ = workspace_work_volume(legacy)
        self.assertEqual(Path('/work') / volume.removeprefix('codex-work-'), workspace_work_root(legacy))
        for layout in (legacy, allocated, deterministic):
            for recovery in (False, True):
                records = helpers.workspace_records([layout.to_dict()], recovery=recovery)
                self.assertEqual(layout.to_dict(), records[0])
                self.assertEqual(workspace_work_root(layout), workspace_work_root(
                    WorkspaceLayout.from_dict(records[0])))
        self.assertNotIn('work_root', legacy.to_dict())
        self.assertEqual('/work/dotfiles-2', allocated.to_dict()['work_root'])

    def test_persisted_work_root_cannot_escape_work_namespace(self):
        record = workspace('/host/project').to_dict()
        for path in ('/tmp/project', '/work', '/work/nested/project', '/work/../escape'):
            with self.subTest(path=path), self.assertRaises(WorkspaceError):
                WorkspaceLayout.from_dict({**record, 'work_root': path})


if __name__ == '__main__':
    unittest.main()
