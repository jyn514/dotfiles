"""Bake metadata preserves source and dependency identities before building."""

from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bake import resolve
from sandbox_runtime import Image
from lima.docker_api import APIError


class Engine:
    def __init__(self, metadata):
        self.metadata = metadata
        self.images = {}
        self.builds = []
        self.producer_status = 0

    def build_platform(self):
        return 'linux/arm64'

    def argv(self, arguments):
        return arguments

    def build_output(self):
        return nullcontext()

    def run_builder(self, command, **kwargs):
        if command[:2] != ['buildx', 'bake']:
            return subprocess.CompletedProcess(command, self.producer_status, '{}')
        if '--print' in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.metadata))
        targets = json.loads(Path(command[command.index('--file') + 1]).read_text())['target']
        self.builds.append(targets)
        for target in targets.values():
            tag = target['tags'][0]
            digest = 'sha256:' + hashlib.sha256((tag + str(len(self.builds))).encode()).hexdigest()
            self.images[tag] = Image(tag + '@' + digest, digest, digest, digest)
        return subprocess.CompletedProcess(command, 0)

    def resolve_image(self, tag):
        if tag not in self.images:
            raise APIError(404, ['image', 'inspect', tag], 'not found')
        return self.images[tag]


class BakeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        (self.repo / '.agents/sandbox').mkdir(parents=True)
        (self.repo / '.agents/sandbox/bake').touch()
        (self.repo / 'ci').mkdir()
        (self.repo / 'ci/base.Dockerfile').write_text('FROM scratch\n')
        (self.repo / 'proxy.Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n')
        self.engine = Engine({'target': {
            'base': {'context': 'ci', 'dockerfile': 'base.Dockerfile', 'tags': ['base:input-one'],
                     'args': {'TOOL_VERSION': '1'}, 'platforms': ['linux/arm64'],
                     'output': [{'type': 'cacheonly'}]},
            'proxy': {'context': '.', 'dockerfile': 'proxy.Dockerfile', 'tags': ['proxy:source-one'],
                      'args': {'BASE_IMAGE': 'base-context'}, 'contexts': {'base-context': 'target:base'}}}})

    def test_warm_launch_skips_build_and_proxy_key_tracks_sources_and_actual_base(self):
        first = resolve(self.engine, self.repo, ['base', 'proxy'])
        self.assertEqual([set(batch) for batch in self.engine.builds], [{'base'}, {'proxy'}])
        base = self.engine.builds[0]['base']
        self.assertEqual(base['context'], str(self.repo / 'ci'))
        self.assertEqual(base['dockerfile'], str(self.repo / 'ci/base.Dockerfile'))
        proxy = self.engine.builds[1]['proxy']
        self.assertEqual(proxy['contexts'], {'base-context': 'docker-image://' + first['base']})
        self.assertEqual(proxy['args'], {'BASE_IMAGE': 'base-context'})
        self.assertEqual(resolve(self.engine, self.repo, ['base', 'proxy']), first)
        self.assertEqual(len(self.engine.builds), 2)

        self.engine.metadata['target']['proxy']['tags'] = ['proxy:source-two']
        changed = resolve(self.engine, self.repo, ['base', 'proxy'])
        self.assertEqual(changed['base'], first['base'])
        self.assertNotEqual(changed['proxy'], first['proxy'])
        self.assertEqual(len(self.engine.builds), 3)

        # A base rebuilt under the same declared input key still invalidates its child.
        del self.engine.images[base['tags'][0]]
        rebuilt = resolve(self.engine, self.repo, ['base', 'proxy'])
        self.assertNotEqual(rebuilt['base'], first['base'])
        self.assertNotEqual(rebuilt['proxy'], changed['proxy'])
        self.assertEqual(len(self.engine.builds), 5)

    def test_changed_build_argument_invalidates_base_and_child(self):
        first = resolve(self.engine, self.repo, ['proxy'])
        self.engine.metadata['target']['base']['args']['TOOL_VERSION'] = '2'
        second = resolve(self.engine, self.repo, ['proxy'])
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.engine.builds), 4)

    def test_invalid_graph_and_unsupported_options_fail_before_builds(self):
        original = deepcopy(self.engine.metadata)
        for override in ({'contexts': {'bad': 'target:missing'}},
                         {'contexts': {'loop': 'target:proxy'}},
                         {'secrets': [{'id': 'secret'}]}, {'platforms': ['linux/amd64']},
                         {'output': [{'type': 'local', 'dest': '/tmp/output'}]},
                         {'dockerfile': 'absent'}):
            with self.subTest(override=override):
                self.engine.metadata = deepcopy(original)
                self.engine.metadata['target']['proxy'].update(override)
                with self.assertRaises((ValueError, OSError)):
                    resolve(self.engine, self.repo, ['proxy'])
                self.assertEqual(self.engine.builds, [])

    def test_failed_declaration_never_builds(self):
        self.engine.producer_status = 7
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            resolve(self.engine, self.repo, ['proxy'])
        self.assertEqual(raised.exception.returncode, 7)
        self.assertEqual(self.engine.builds, [])

    def test_engine_error_is_not_a_cache_miss(self):
        def unavailable(tag):
            raise APIError(500, ['image', 'inspect', tag], 'engine failure')
        self.engine.resolve_image = unavailable
        with self.assertRaises(APIError):
            resolve(self.engine, self.repo, ['proxy'])
        self.assertEqual(self.engine.builds, [])


if __name__ == '__main__':
    unittest.main()
