"""Bake metadata preserves source and dependency identities before building."""

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bake
from bake import resolve
from docker_runtime import BuildError
from sandbox_runtime import Image, RuntimeError
from lima.docker_api import APIError


class Engine:
    provider = 'test-engine'

    def __init__(self, metadata):
        self.metadata = metadata
        self.images = {}
        self.builds = []
        self.built_files = []
        self.producer_status = 0
        self.build_status = 0
        self.before_build = None
        self.upstream = 'sha256:' + '1' * 64
        self.upstream_calls = []

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
        if self.before_build is not None:
            self.before_build()
            self.before_build = None
        if self.build_status:
            return subprocess.CompletedProcess(command, self.build_status)
        targets = json.loads(Path(command[command.index('--file') + 1]).read_text())['target']
        self.builds.append(targets)
        self.built_files.append({
            name: (Path(target['context']) / Path(target['dockerfile']).relative_to(target['context'])).read_bytes()
            for name, target in targets.items()
        })
        for target in targets.values():
            tag = target['tags'][0]
            digest = 'sha256:' + hashlib.sha256((tag + str(len(self.builds))).encode()).hexdigest()
            self.images[tag] = Image(tag + '@' + digest, digest, digest, digest)
        return subprocess.CompletedProcess(command, 0)

    def resolve_image(self, tag):
        if tag not in self.images:
            raise APIError(404, ['image', 'inspect', tag], 'not found')
        return self.images[tag]

    def upstream_image(self, reference):
        self.upstream_calls.append(reference)
        return reference.split(':', 1)[0] + '@' + self.upstream


class BakeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        self.cache_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache_temporary.cleanup)
        cache = Path(self.cache_temporary.name)
        cache.chmod(0o700)
        patcher = mock.patch.object(bake, '_cache_directory', return_value=cache)
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertNotEqual(base['context'], str(self.repo / 'ci'))
        self.assertTrue(base['dockerfile'].startswith(base['context'] + '/'))
        self.assertEqual(self.engine.built_files[0]['base'], b'FROM scratch\n')
        proxy = self.engine.builds[1]['proxy']
        self.assertEqual(proxy['contexts'], {'base-context': 'docker-image://' + first['base']})
        self.assertEqual(proxy['args'], {'BASE_IMAGE': 'base-context'})
        self.assertEqual(resolve(self.engine, self.repo, ['base', 'proxy']), first)
        self.assertEqual(len(self.engine.builds), 2)

        self.engine.metadata['target']['proxy']['tags'] = ['proxy:source-two']
        changed = resolve(self.engine, self.repo, ['base', 'proxy'])
        self.assertEqual(changed['base'], first['base'])
        self.assertEqual(changed['proxy'], first['proxy'])
        self.assertEqual(len(self.engine.builds), 2)

        # A base rebuilt under the same declared input key still invalidates its child.
        del self.engine.images[base['tags'][0]]
        rebuilt = resolve(self.engine, self.repo, ['base', 'proxy'])
        self.assertNotEqual(rebuilt['base'], first['base'])
        self.assertNotEqual(rebuilt['proxy'], changed['proxy'])
        self.assertEqual(len(self.engine.builds), 4)

    def test_source_bytes_invalidate_without_producer_tag_change(self):
        first = resolve(self.engine, self.repo, ['base'])
        (self.repo / 'ci/base.Dockerfile').write_text('FROM scratch\n# changed\n')
        second = resolve(self.engine, self.repo, ['base'])
        self.assertNotEqual(first, second)
        built = next(batch['base'] for batch in reversed(self.engine.built_files) if 'base' in batch)
        self.assertEqual(built, b'FROM scratch\n# changed\n')

    def test_context_shape_modes_and_symlink_targets_invalidate(self):
        identities = [resolve(self.engine, self.repo, ['base'])['base']]
        first = self.repo / 'ci/first'
        first.write_text('one')
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        first.chmod(0o755)
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        second = first.rename(self.repo / 'ci/second')
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        alternative = self.repo / 'ci/alternative'
        alternative.write_text('one')
        link = self.repo / 'ci/link'
        link.symlink_to('second')
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        link.unlink()
        link.symlink_to('alternative')
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        second.unlink()
        identities.append(resolve(self.engine, self.repo, ['base'])['base'])
        self.assertEqual(len(identities), len(set(identities)))

    def test_local_named_context_is_captured_and_invalidates(self):
        assets = self.repo / 'assets'
        assets.mkdir()
        (assets / 'value').write_text('one')
        self.engine.metadata['target']['base']['contexts'] = {'assets': 'assets'}
        first = resolve(self.engine, self.repo, ['base'])
        built = next(batch['base'] for batch in reversed(self.engine.builds) if 'base' in batch)
        captured = built['contexts']['assets']
        self.assertNotEqual(captured, str(assets))
        (assets / 'value').write_text('two')
        self.assertNotEqual(resolve(self.engine, self.repo, ['base']), first)

    def test_mutable_image_context_is_pinned_until_refresh(self):
        self.engine.metadata['target']['base']['contexts'] = {
            'tool': 'docker-image://busybox:stable',
        }
        first = resolve(self.engine, self.repo, ['base'])
        self.assertEqual(['busybox:stable'], self.engine.upstream_calls)
        self.assertEqual(first, resolve(self.engine, self.repo, ['base']))
        self.assertEqual(['busybox:stable'], self.engine.upstream_calls)
        self.engine.upstream = 'sha256:' + '2' * 64
        refreshed = resolve(self.engine, self.repo, ['base'], operation='refresh')
        self.assertNotEqual(first, refreshed)
        self.assertEqual(['busybox:stable', 'busybox:stable'], self.engine.upstream_calls)
        built = next(batch['base'] for batch in reversed(self.engine.builds) if 'base' in batch)
        self.assertEqual(
            'docker-image://busybox@sha256:' + '2' * 64,
            built['contexts']['tool'],
        )

    def test_checkout_mutation_after_capture_does_not_change_built_bytes(self):
        source = self.repo / 'ci/base.Dockerfile'
        self.engine.before_build = lambda: source.write_text('FROM scratch\n# too late\n')
        resolve(self.engine, self.repo, ['base'])
        self.assertEqual(b'FROM scratch\n', self.engine.built_files[0]['base'])

    def test_ignore_files_and_escaping_links_are_rejected(self):
        for path, setup in (
            (self.repo / 'ci/.dockerignore', lambda path: path.write_text('ignored')),
            (self.repo / 'ci/base.Dockerfile.dockerignore', lambda path: path.write_text('ignored')),
            (self.repo / 'ci/escape', lambda path: path.symlink_to('../proxy.Dockerfile')),
        ):
            with self.subTest(path=path.name):
                setup(path)
                with self.assertRaises(RuntimeError):
                    resolve(self.engine, self.repo, ['base'])
                path.unlink()

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

    def test_failed_build_publishes_no_cache_record(self):
        self.engine.build_status = 23
        with self.assertRaises(BuildError):
            resolve(self.engine, self.repo, ['base'])
        records = [path for path in bake._cache_directory().glob('*.json')
                   if path.name != 'upstream-pins.json']
        self.assertEqual([], records)

    def test_engine_error_is_not_a_cache_miss(self):
        def unavailable(tag):
            raise APIError(500, ['image', 'inspect', tag], 'engine failure')
        self.engine.resolve_image = unavailable
        with self.assertRaises(APIError):
            resolve(self.engine, self.repo, ['proxy'])
        self.assertEqual(self.engine.builds, [])

    def test_concurrent_misses_publish_once(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(
                lambda _: resolve(self.engine, self.repo, ['base']), range(2),
            ))
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, sum('base' in batch for batch in self.engine.builds))

    def test_upstream_pins_refresh_and_clean_are_explicit(self):
        (self.repo / 'ci/base.Dockerfile').write_text(
            '# syntax=docker/dockerfile:1.7\nFROM alpine:3.22\n',
        )
        first = resolve(self.engine, self.repo, ['base'])
        self.assertEqual(['docker/dockerfile:1.7', 'alpine:3.22'], self.engine.upstream_calls)
        self.assertEqual(first, resolve(self.engine, self.repo, ['base']))
        self.assertEqual(['docker/dockerfile:1.7', 'alpine:3.22'], self.engine.upstream_calls)

        self.engine.upstream = 'sha256:' + '2' * 64
        refreshed = resolve(self.engine, self.repo, ['base'], operation='refresh')
        self.assertNotEqual(first, refreshed)
        self.assertEqual(
            ['docker/dockerfile:1.7', 'alpine:3.22', 'docker/dockerfile:1.7', 'alpine:3.22'],
            self.engine.upstream_calls,
        )

        before = len(self.engine.builds)
        resolve(self.engine, self.repo, ['base'], operation='clean')
        self.assertGreater(len(self.engine.builds), before)
        built = next(batch['base'] for batch in reversed(self.engine.built_files) if 'base' in batch)
        self.assertIn('@sha256:' + '2' * 64, built.decode())

    def test_failed_refresh_does_not_publish_new_upstream_pin(self):
        (self.repo / 'ci/base.Dockerfile').write_text('FROM alpine:3.22\n')
        first = resolve(self.engine, self.repo, ['base'])
        self.engine.upstream = 'sha256:' + '2' * 64
        self.engine.build_status = 23
        with self.assertRaises(BuildError):
            resolve(self.engine, self.repo, ['base'], operation='refresh')
        self.engine.build_status = 0
        self.assertEqual(first, resolve(self.engine, self.repo, ['base']))
        self.assertEqual(['alpine:3.22', 'alpine:3.22'], self.engine.upstream_calls)

    def test_late_ordinary_resolution_cannot_overwrite_refreshed_pin(self):
        key = 'test-engine\0linux/arm64\0alpine:3.22'
        refreshed = 'alpine@sha256:' + '2' * 64
        stale = 'alpine@sha256:' + '1' * 64
        bake._publish_pins({key: (refreshed, True)})
        bake._publish_pins({key: (stale, False)})
        pins = json.loads((bake._cache_directory() / 'upstream-pins.json').read_text())
        self.assertEqual(refreshed, pins[key])


if __name__ == '__main__':
    unittest.main()
