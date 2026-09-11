"""Resolve repository Bake declarations and cache targets in the selected engine."""

from copy import deepcopy
from graphlib import TopologicalSorter
import hashlib
import json
from pathlib import Path
import re
import tempfile

from sandbox_runtime import RuntimeError
from docker_runtime import BuildError
from lima.docker_api import APIError


def target_graph(metadata, requested, platform):
    """Validate the supported local-build contract before starting any builds."""
    if not isinstance(metadata, dict):
        raise RuntimeError('Bake output must be an object')
    targets = metadata.get('target')
    if not isinstance(targets, dict) or not set(requested) <= targets.keys():
        raise RuntimeError('Bake output is missing requested targets')
    graph = {}
    allowed = {'context', 'dockerfile', 'args', 'labels', 'tags', 'platforms',
               'contexts', 'target', 'output'}
    for name, target in targets.items():
        if not isinstance(target, dict) or target.keys() - allowed:
            raise RuntimeError(f'unsupported Bake options for {name}')
        if target.get('platforms', [platform]) != [platform]:
            raise RuntimeError(f'Bake target {name} must use engine platform {platform}')
        for key in ('args', 'labels', 'contexts'):
            values = target.get(key, {})
            if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                     for k, v in values.items()):
                raise RuntimeError(f'Bake target {name} has invalid {key}')
        tags = target.get('tags', [])
        if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) for tag in tags):
            raise RuntimeError(f'Bake target {name} needs an input-keyed tag')
        for key, default in (('context', '.'), ('dockerfile', 'Dockerfile')):
            value = target.get(key, default)
            if not isinstance(value, str) or not value or '://' in value or value == '-':
                raise RuntimeError(f'Bake target {name} needs a local {key}')
        if 'target' in target and not isinstance(target['target'], str):
            raise RuntimeError(f'Bake target {name} has invalid stage')
        if target.get('output', []) not in ([], [{'type': 'cacheonly'}], [{'type': 'docker'}]):
            raise RuntimeError(f'Bake target {name} cannot publish external outputs')
        dependencies = {}
        for alias, context in target.get('contexts', {}).items():
            if not context.startswith('target:') or context[7:] not in targets:
                raise RuntimeError(f'Bake context {name}:{alias} must name a declared target')
            dependencies[alias] = context[7:]
        graph[name] = set(dependencies.values())
    sorter = TopologicalSorter(graph)
    sorter.prepare()
    return sorter


def resolve(runtime, repo, requested):
    """One fresh declaration, one engine, and one immutable result per target."""
    repo = Path(repo).resolve()
    requested = list(dict.fromkeys(requested))
    if not requested:
        return {}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in requested):
        raise RuntimeError('invalid Bake target name')
    producer = repo / '.agents/sandbox/bake'
    if not producer.is_file():
        raise RuntimeError(f'{producer} must emit a fresh Bake declaration with input-keyed tags')
    source = runtime.run_builder([str(producer)], cwd=repo)
    source.check_returncode()
    platform = runtime.build_platform()
    with tempfile.TemporaryDirectory(prefix='sandbox-bake-') as directory:
        try:
            json.loads(source.stdout)
            suffix = 'json'
        except json.JSONDecodeError:
            suffix = 'hcl'
        definition = Path(directory) / ('docker-bake.' + suffix)
        definition.write_text(source.stdout)
        printed = runtime.run_builder(runtime.argv([
            'buildx', 'bake', '--builder', 'default', '--print', '--progress=quiet', '--file', str(definition),
            '--var', 'BUILDPLATFORM=' + platform, *requested]), cwd=repo)
        printed.check_returncode()
        metadata = json.loads(printed.stdout)
        sorter = target_graph(metadata, requested, platform)
        # Resolve all local paths before the first build, including Dockerfiles
        # relative to their contexts rather than the temporary declaration.
        paths = {}
        for name, target in metadata['target'].items():
            context = (repo / target.get('context', '.')).resolve(strict=True)
            dockerfile = (context / target.get('dockerfile', 'Dockerfile')).resolve(strict=True)
            if not context.is_dir() or not dockerfile.is_file():
                raise RuntimeError(f'Bake target {name} has invalid build paths')
            paths[name] = context, dockerfile
        images = {}
        while sorter.is_active():
            ready = sorter.get_ready()
            missing = {}
            tags = {}
            for name in ready:
                target = deepcopy(metadata['target'][name])
                target.pop('output', None)
                target['platforms'] = [platform]
                dependencies = {alias: images[value[7:]]
                                for alias, value in target.get('contexts', {}).items()}
                # Input-keyed repository tags describe sources; actual dependency
                # IDs also invalidate children when the same base key is rebuilt.
                identity = {**target, 'contexts': {alias: image.config for alias, image in dependencies.items()}}
                key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                tag = 'sandbox-bake:' + key
                try:
                    images[name] = runtime.resolve_image(tag)
                except APIError as error:
                    if error.status != 404:
                        raise
                    context, dockerfile = paths[name]
                    target.update(context=str(context), dockerfile=str(dockerfile), tags=[tag],
                                  contexts={alias: 'docker-image://' + image.reference
                                            for alias, image in dependencies.items()},
                                  output=[{'type': 'docker'}])
                    missing[name] = target
                    tags[name] = tag
            if missing:
                definition = Path(directory) / 'build.json'
                definition.write_text(json.dumps({'target': missing}))
                with runtime.build_output():
                    result = runtime.run_builder(runtime.argv([
                        'buildx', 'bake', '--builder', 'default', '--file', str(definition), '--provenance=false', *missing]),
                        cwd=repo, capture=False)
                    if result.returncode:
                        raise BuildError(result.returncode, result.args)
                images.update({name: runtime.resolve_image(tag) for name, tag in tags.items()})
            sorter.done(*ready)
        return {name: images[name].reference for name in requested}
