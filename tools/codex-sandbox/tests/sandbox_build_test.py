"""Repository build graphs keep dependencies and verify their publication."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sandbox_build import BuildBatch, prepare_launch


class BatchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        definition = self.root / '.agents/sandbox/docker-bake.hcl'
        definition.parent.mkdir(parents=True)
        definition.touch()
        self.runtime = Mock()
        self.runtime.bake_targets.return_value = {
            'base': {'context': '.', 'dockerfile': 'base.Dockerfile'},
            'bug': {'context': '.', 'contexts': {'parent': 'target:base'}}}

    def test_one_graph_preserves_repository_dependencies_and_trusted_targets(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'commands': {'bug': {'image-target': 'bug'}}}))
        state = SimpleNamespace(repository=self.root, manifest=manifest, uid=501, gid=20, term='xterm')
        image = SimpleNamespace(content='digest', reference='image@digest')
        self.runtime.inspect_image.return_value = image
        self.runtime.bake.return_value = {name: {'containerimage.digest': 'digest'}
            for name in ('repo-base', 'repo-bug', 'trusted-auth', 'trusted-agent')}
        self.assertEqual(prepare_launch(self.runtime, state, self.root),
                         ('image@digest', 'image@digest', {'bug': 'image@digest'}))
        targets = self.runtime.bake.call_args.args[0]
        self.runtime.bake.assert_called_once()
        self.assertEqual(targets['repo-bug']['contexts'], {'parent': 'target:repo-base'})
        self.assertEqual(targets['trusted-agent']['contexts'], {'sandbox-base': 'target:repo-base'})
        # A warm tag is not proof that its Dockerfile or copied files are unchanged.
        prepare_launch(self.runtime, state, self.root)
        self.assertEqual(self.runtime.bake.call_count, 2)

    def test_repository_exporters_and_tags_do_not_publish_outside_local_engine(self):
        batch = BuildBatch(self.runtime, self.root)
        batch.add('base', {'tags': ['registry.example/production'],
                          'output': [{'type': 'registry'}], 'cache-to': ['type=registry,ref=cache']})
        target = batch.targets['base']
        self.assertEqual(target['output'], [{'type': 'docker'}])
        self.assertEqual(target['cache-to'], [])
        self.assertTrue(target['tags'][0].startswith('codex-sandbox-bake:'))

    def test_retagged_output_cannot_be_published_as_bake_result(self):
        self.runtime.inspect_image.return_value = SimpleNamespace(content='replacement')
        self.runtime.bake.return_value = {'agent': {'containerimage.digest': 'built'}}
        batch = BuildBatch(self.runtime, self.root)
        batch.add('agent', {'context': '.'})
        with self.assertRaisesRegex(ValueError, 'differs'):
            batch.finish()

    def test_missing_repository_target_fails_before_build(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'commands': {'bug': {'image-command': ['old-builder']}}}))
        state = SimpleNamespace(repository=self.root, manifest=manifest)
        with self.assertRaisesRegex(ValueError, 'image-target'):
            prepare_launch(self.runtime, state, self.root)
        self.runtime.bake.assert_not_called()


if __name__ == '__main__':
    unittest.main()
