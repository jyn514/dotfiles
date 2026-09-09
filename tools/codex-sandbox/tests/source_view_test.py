"""Source browsing must not obstruct worktree overlays or modify host directories."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_view import source_mounts


class SourceViewTest(unittest.TestCase):
    def test_existing_destinations_keep_the_live_parent_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src/project').mkdir(parents=True)
            mounts = source_mounts(root / 'src', [Path('/src/project')], root / 'view')
            self.assertEqual(mounts, ['--mount', f'type=bind,src={root}/src,dst=/src,readonly'])
            self.assertFalse((root / 'view').exists())

    def test_missing_nested_metadata_splits_only_its_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'src'
            (source / 'team').mkdir(parents=True)
            (source / 'sibling').mkdir()
            (source / 'team/file').touch()
            (source / 'alias').symlink_to('sibling')
            mounts = source_mounts(source, [Path('/src/repository'), Path('/src/team/main/.git')], root / 'view')
            self.assertTrue((root / 'view/team/main/.git').is_dir())
            self.assertEqual(os.readlink(root / 'view/alias'), 'sibling')
            self.assertIn(f'type=bind,src={source}/sibling,dst=/src/sibling,readonly', mounts)
            self.assertIn(f'type=bind,src={source}/team/file,dst=/src/team/file,readonly', mounts)
            self.assertNotIn(f'type=bind,src={source}/team,dst=/src/team,readonly', mounts)
            self.assertFalse((source / 'team/main').exists())

    def test_existing_fallback_content_cannot_overlay_the_active_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src/repository').mkdir(parents=True)
            (root / 'src/repository/old').touch()
            mounts = source_mounts(root / 'src', [Path('/src/repository'), Path('/src/main/.git')], root / 'view')
            self.assertFalse(any('dst=/src/repository' in argument for argument in mounts))
            self.assertFalse((root / 'view/repository/old').exists())

    def test_missing_path_cannot_follow_a_host_symlink_out_of_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'external').mkdir()
            (root / 'src/link').symlink_to(root / 'external')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                source_mounts(root / 'src', [Path('/src/link/missing')], root / 'view')
            self.assertFalse((root / 'external/missing').exists())


if __name__ == '__main__':
    unittest.main()
