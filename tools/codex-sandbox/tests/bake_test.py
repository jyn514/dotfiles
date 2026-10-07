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
        self.context_files = []
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
        self.context_files.append({
            name: {path.relative_to(target['context']).as_posix(): path.read_bytes()
                   for path in Path(target['context']).rglob('*') if path.is_file()}
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

    def image_if_available(self, reference):
        return self.images.get(reference)


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

    def test_live_hcl_reaches_buildx_without_json_string_encoding(self):
        source = 'target "base" { context = "ci" }\n'
        run_builder = self.engine.run_builder

        def inspect_declaration(command, **kwargs):
            if '--print' in command:
                definition = Path(command[command.index('--file') + 1])
                self.assertEqual(definition.suffix, '.hcl')
                self.assertEqual(definition.read_text(), source)
            return run_builder(command, **kwargs)

        with mock.patch.object(self.engine, 'run_builder', side_effect=inspect_declaration):
            self.assertIn('base', resolve(self.engine, self.repo, ['base'], declaration=source))

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

    def test_escaping_context_link_is_rejected(self):
        (self.repo / 'ci/escape').symlink_to('../proxy.Dockerfile')
        with self.assertRaises(RuntimeError):
            resolve(self.engine, self.repo, ['base'])

    def test_ignore_filters_before_capture_and_ignored_changes_preserve_cache(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        (context / '.dockerignore').write_text('target\n')
        (context / 'target').mkdir()
        ignored = context / 'target/large'
        ignored.write_text('large build artifact')
        scan = bake.os.scandir

        def no_ignored_walk(path):
            if not isinstance(path, int):
                self.assertNotEqual(Path(path), context / 'target')
            return scan(path)

        with mock.patch.object(bake.os, 'scandir', side_effect=no_ignored_walk):
            first = resolve(self.engine, self.repo, ['base'])
        self.assertEqual({'base.Dockerfile', '.dockerignore'},
                         set(self.engine.context_files[-1]['base']))
        ignored.write_text('changed')
        (context / 'target/new').touch()
        self.assertEqual(first, resolve(self.engine, self.repo, ['base']))
        (context / 'included').write_text('one')
        self.assertNotEqual(first, resolve(self.engine, self.repo, ['base']))

    def test_known_sdk_divergences_match_buildkit_payloads(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        cases = [
            ('README.md\n', ['README.md', 'readme.md'], {'readme.md'}),
            ('**\n!**/a.txt\n', ['foo/a.txt', 'foo/bar/a.txt', 'target/a.txt'],
             {'foo/a.txt', 'foo/bar/a.txt', 'target/a.txt'}),
            ('**/cache\n!cache/keep.txt\n', ['cache/drop.txt', 'cache/keep.txt'],
             {'cache/keep.txt'}),
        ]
        for rules, files, expected in cases:
            with self.subTest(rules=rules):
                (context / '.dockerignore').write_text(rules)
                for name in files:
                    path = context / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name)
                resolve(self.engine, self.repo, ['base'])
                actual = set(self.engine.context_files[-1]['base'])
                self.assertEqual(expected, actual & set(files))
                self.assertIn('base.Dockerfile', actual)
                self.assertIn('.dockerignore', actual)
                for name in files:
                    (context / name).unlink()

    def test_specific_ignore_overrides_default_and_rule_changes_invalidate(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        (context / '.dockerignore').write_text('keep\n')
        specific = context / 'base.Dockerfile.dockerignore'
        specific.write_text('drop\n')
        (context / 'keep').touch()
        (context / 'drop').touch()
        first = resolve(self.engine, self.repo, ['base'])
        actual = self.engine.context_files[-1]['base']
        self.assertIn('keep', actual)
        self.assertNotIn('drop', actual)
        specific.write_text('keep\n')
        self.assertNotEqual(first, resolve(self.engine, self.repo, ['base']))
        actual = self.engine.context_files[-1]['base']
        self.assertNotIn('keep', actual)
        self.assertIn('drop', actual)

    def test_comments_bom_and_ordered_exceptions(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        (context / '.dockerignore').write_text('\ufeff# comment\n\n drop/ \n!drop/keep\ndrop/keep\n')
        (context / 'drop').mkdir()
        (context / 'drop/keep').touch()
        (context / 'visible').touch()
        resolve(self.engine, self.repo, ['base'])
        actual = self.engine.context_files[-1]['base']
        self.assertIn('visible', actual)
        self.assertNotIn('drop/keep', actual)

    def test_ignored_special_files_do_not_block_capture(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        bake.os.mkfifo(context / 'pipe')
        (context / '.dockerignore').write_text('pipe\n')
        resolve(self.engine, self.repo, ['base'])
        self.assertNotIn('pipe', self.engine.context_files[-1]['base'])
        (context / '.dockerignore').write_text('')
        with self.assertRaises(RuntimeError):
            resolve(self.engine, self.repo, ['base'])

    def test_explicit_inputs_still_apply_ignore_and_keep_build_controls(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        (context / '.dockerignore').write_text('**\n!keep\n')
        (context / 'keep').touch()
        (context / 'drop').touch()
        resolve(self.engine, self.repo, ['base'], captures={'base': ['keep', 'drop']})
        self.assertEqual({'base.Dockerfile', '.dockerignore', 'keep'},
                         set(self.engine.context_files[-1]['base']))

    def test_ignore_snapshot_uses_the_rules_read_before_checkout_mutation(self):
        self.engine.metadata['target'].pop('proxy')
        context = self.repo / 'ci'
        ignore = context / '.dockerignore'
        ignore.write_text('drop\n')
        (context / 'keep').touch()
        (context / 'drop').touch()
        read_bytes = Path.read_bytes

        def read_and_mutate(path):
            data = read_bytes(path)
            if path == ignore:
                ignore.write_text('keep\n')
            return data

        with mock.patch.object(Path, 'read_bytes', read_and_mutate):
            resolve(self.engine, self.repo, ['base'])
        actual = self.engine.context_files[-1]['base']
        self.assertEqual(b'drop\n', actual['.dockerignore'])
        self.assertIn('keep', actual)
        self.assertNotIn('drop', actual)

    def test_invalid_ignore_file_fails_before_building(self):
        self.engine.metadata['target'].pop('proxy')
        ignore = self.repo / 'ci/.dockerignore'
        for contents in (b'!\n', b'\xff'):
            with self.subTest(contents=contents):
                ignore.write_bytes(contents)
                with self.assertRaisesRegex(RuntimeError, 'invalid Docker ignore file'):
                    resolve(self.engine, self.repo, ['base'])
        ignore.unlink()
        ignore.symlink_to('base.Dockerfile')
        with self.assertRaisesRegex(RuntimeError, 'invalid Docker ignore file'):
            resolve(self.engine, self.repo, ['base'])
        self.assertEqual([], self.engine.builds)

    def test_external_context_symlink_is_ignored(self):
        link = self.repo / 'ci/container-python'
        link.symlink_to('/src/personal/lapwing/stint/.uv-python/python')

        resolve(self.engine, self.repo, ['base'])

        captured = next(batch['base'] for batch in reversed(self.engine.builds) if 'base' in batch)
        self.assertFalse((Path(captured['context']) / 'container-python').exists())

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

    def test_local_upstream_avoids_registry_until_refresh(self):
        (self.repo / 'ci/base.Dockerfile').write_text('FROM alpine:3.22\n')
        digest = 'sha256:' + '3' * 64
        self.engine.images['alpine:3.22'] = Image('alpine@' + digest, digest, digest, digest)
        first = resolve(self.engine, self.repo, ['base'])
        self.assertEqual([], self.engine.upstream_calls)
        del self.engine.images['alpine:3.22']
        self.assertEqual(first, resolve(self.engine, self.repo, ['base']))
        self.assertEqual([], self.engine.upstream_calls)
        self.assertNotEqual(first, resolve(self.engine, self.repo, ['base'], operation='refresh'))
        self.assertEqual(['alpine:3.22'], self.engine.upstream_calls)

    def test_failed_build_retains_successful_ordinary_resolution(self):
        (self.repo / 'ci/base.Dockerfile').write_text('FROM alpine:3.22\n')
        self.engine.build_status = 23
        for _ in range(2):
            with self.assertRaises(BuildError):
                resolve(self.engine, self.repo, ['base'])
        self.assertEqual(['alpine:3.22'], self.engine.upstream_calls)

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
