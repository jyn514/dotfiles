"""Resolve repository Bake declarations and cache targets in the selected engine."""

from copy import deepcopy
from contextlib import ExitStack, contextmanager
import fcntl
from graphlib import TopologicalSorter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from sandbox_runtime import RuntimeError
from docker_runtime import BuildError
from lima.docker_api import APIError

CACHE_CONTRACT = 2


def _cache_directory():
    directory = Path(tempfile.gettempdir()).resolve() / f'codex-sandbox-images-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError(f'unsafe Bake cache directory: {directory}')
    return directory


@contextmanager
def _cache_locks(keys):
    with ExitStack() as stack:
        for key in sorted(keys):
            lock = stack.enter_context((_cache_directory() / (key + '.lock')).open('a+b'))
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _record(key, image):
    directory = _cache_directory()
    temporary = directory / (key + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps({'version': CACHE_CONTRACT, 'image': image.reference}) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(directory / (key + '.json'))


def _write_atomic(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _pin_upstream(runtime, reference, *, refresh, pending=None):
    if '@sha256:' in reference or re.fullmatch(r'sha256:[0-9a-f]{64}', reference):
        return reference
    pins_path = _cache_directory() / 'upstream-pins.json'
    with _cache_locks(['upstream-pins']):
        pins = json.loads(pins_path.read_text()) if pins_path.exists() else {}
        if not isinstance(pins, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                 for k, v in pins.items()):
            raise RuntimeError('invalid upstream image pin record')
        pin_key = runtime.provider + '\0' + runtime.build_platform() + '\0' + reference
        if pending is not None and pin_key in pending:
            return pending[pin_key][0]
        pinned = runtime.upstream_image(reference) if refresh or pin_key not in pins else pins[pin_key]
        if '@sha256:' not in pinned and not re.fullmatch(r'sha256:[0-9a-f]{64}', pinned):
            raise RuntimeError(f'upstream image did not resolve immutably: {reference}')
        if pins.get(pin_key) != pinned:
            if pending is not None:
                pending[pin_key] = (pinned, refresh)
            else:
                pins[pin_key] = pinned
                _write_atomic(pins_path, pins)
        return pinned


def _publish_pins(pending):
    if not pending:
        return
    pins_path = _cache_directory() / 'upstream-pins.json'
    with _cache_locks(['upstream-pins']):
        pins = json.loads(pins_path.read_text()) if pins_path.exists() else {}
        if not isinstance(pins, dict):
            raise RuntimeError('invalid upstream image pin record')
        for key, (pinned, refresh) in pending.items():
            if refresh or key not in pins:
                pins[key] = pinned
        _write_atomic(pins_path, pins)


def _pin_dockerfile(runtime, dockerfile, arguments, local_images, *, refresh, pending=None):
    """Resolve mutable FROM references once and rewrite the captured Dockerfile."""
    variables = dict(arguments)
    stages = set()
    output = []
    for raw in dockerfile.read_text(encoding='utf-8').splitlines(keepends=True):
        line = raw.rstrip('\n')
        syntax = re.fullmatch(r'(\s*#\s*syntax=)(\S+)\s*', line, re.IGNORECASE)
        if syntax:
            output.append(syntax.group(1) + _pin_upstream(
                runtime, syntax.group(2), refresh=refresh, pending=pending,
            ) + ('\n' if raw.endswith('\n') else ''))
            continue
        arg = re.fullmatch(r'\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:=(\S+))?\s*', line)
        if arg and arg.group(1) not in variables and arg.group(2) is not None:
            variables[arg.group(1)] = arg.group(2)
        match = re.fullmatch(r'(\s*FROM\s+(?:--platform=\S+\s+)?)(\S+)(.*)', line, re.IGNORECASE)
        if not match:
            output.append(raw)
            continue
        image = re.sub(
            r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)',
            lambda item: variables.get(item.group(1) or item.group(2), item.group(0)),
            match.group(2),
        )
        if '$' in image:
            raise RuntimeError(f'unresolved Dockerfile FROM expression: {image}')
        if image.lower() != 'scratch' and image not in stages and image not in local_images:
            image = _pin_upstream(runtime, image, refresh=refresh, pending=pending)
        stage = re.search(r'\s+AS\s+([A-Za-z0-9_.-]+)\s*$', match.group(3), re.IGNORECASE)
        if stage:
            stages.add(stage.group(1))
        output.append(match.group(1) + image + match.group(3) + ('\n' if raw.endswith('\n') else ''))
    rewritten = ''.join(output)
    dockerfile.write_text(rewritten, encoding='utf-8')
    return rewritten


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
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise RuntimeError(f'Bake target {name} has invalid tags')
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
            if context.startswith('target:'):
                if context[7:] not in targets:
                    raise RuntimeError(f'Bake context {name}:{alias} names an absent target')
                dependencies[alias] = context[7:]
            elif '://' in context and not context.startswith('docker-image://'):
                raise RuntimeError(f'Bake context {name}:{alias} uses an unsupported source')
        graph[name] = set(dependencies.values())
    sorter = TopologicalSorter(graph)
    sorter.prepare()
    return sorter


def _capture(root, source, destination, identity, include=None):
    """Copy one complete local context while hashing its filesystem representation."""
    source = source.resolve(strict=True)
    if not source.is_dir() or not source.is_relative_to(root):
        raise RuntimeError('Bake contexts must stay beneath the repository root')
    for ignored in ('.dockerignore',):
        if (source / ignored).exists() or (source / ignored).is_symlink():
            raise RuntimeError(f'captured Bake context cannot use {ignored}')
    destination.mkdir(parents=True)
    if include is None:
        paths = list(source.rglob('*'))
    else:
        paths = []
        for relative in include:
            path = (source / relative).resolve(strict=True)
            if not path.is_relative_to(source) or not path.is_file():
                raise RuntimeError(f'captured Bake input is invalid: {relative}')
            for parent in reversed(path.relative_to(source).parents[:-1]):
                candidate = source / parent
                if candidate not in paths:
                    paths.append(candidate)
            paths.append(path)
    for path in sorted(set(paths), key=lambda item: item.relative_to(source).as_posix().encode()):
        relative = path.relative_to(source)
        mode = path.lstat().st_mode
        identity.update(relative.as_posix().encode() + b'\0' + str(stat.S_IMODE(mode)).encode() + b'\0')
        target = destination / relative
        if stat.S_ISDIR(mode):
            target.mkdir()
            identity.update(b'd\0')
        elif stat.S_ISREG(mode):
            data = path.read_bytes()
            identity.update(b'f\0' + hashlib.sha256(data).digest())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(stat.S_IMODE(mode))
        elif stat.S_ISLNK(mode):
            link = path.readlink()
            resolved = (path.parent / link).resolve(strict=True)
            if not resolved.is_relative_to(source):
                raise RuntimeError(f'Bake context link escapes capture: {relative}')
            identity.update(b'l\0' + str(link).encode())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link, target_is_directory=resolved.is_dir())
        else:
            raise RuntimeError(f'Bake context {source} contains a special file: {relative}')
    return destination


def resolve(runtime, repo, requested, *, declaration=None, file=None, captures=None,
            operation='resolve'):
    if operation == 'refresh':
        with _cache_locks(['upstream-refresh']):
            return _resolve(runtime, repo, requested, declaration=declaration, file=file,
                            captures=captures, operation=operation)
    return _resolve(runtime, repo, requested, declaration=declaration, file=file,
                    captures=captures, operation=operation)


def _resolve(runtime, repo, requested, *, declaration=None, file=None, captures=None,
             operation='resolve'):
    """One fresh declaration, one engine, and one immutable result per target."""
    repo = Path(repo).resolve()
    requested = list(dict.fromkeys(requested))
    if not requested:
        return {}
    if operation not in {'resolve', 'refresh', 'clean'}:
        raise ValueError(f'unsupported Bake operation: {operation}')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in requested):
        raise RuntimeError('invalid Bake target name')
    if declaration is None and file is None:
        producer = repo / '.agents/sandbox/bake'
        if not producer.is_file():
            raise RuntimeError(f'{producer} must emit a fresh Bake declaration with input-keyed tags')
        result = runtime.run_builder([str(producer)], cwd=repo)
        result.check_returncode()
        source = result.stdout
    elif declaration is not None:
        source = declaration if isinstance(declaration, str) else json.dumps(declaration)
    else:
        definition = (repo / file).resolve(strict=True)
        if not definition.is_file() or not definition.is_relative_to(repo):
            raise RuntimeError('Bake resolver file must stay beneath the repository root')
        source = definition.read_text(encoding='utf-8')
    platform = runtime.build_platform()
    with tempfile.TemporaryDirectory(prefix='sandbox-bake-') as directory_name:
        directory = Path(directory_name).resolve()
        try:
            json.loads(source)
            suffix = 'json'
        except json.JSONDecodeError:
            suffix = 'hcl'
        definition = directory / ('docker-bake.' + suffix)
        definition.write_text(source)
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
            specific_ignore = dockerfile.with_name(dockerfile.name + '.dockerignore')
            if specific_ignore.exists() or specific_ignore.is_symlink():
                raise RuntimeError(f'captured Bake context cannot use {specific_ignore.name}')
        images = {}
        pending_pins = {}
        while sorter.is_active():
            ready = sorter.get_ready()
            missing = {}
            tags = {}
            for name in ready:
                target = deepcopy(metadata['target'][name])
                target.pop('output', None)
                target['platforms'] = [platform]
                dependencies = {alias: images[value[7:]]
                                for alias, value in target.get('contexts', {}).items()
                                if value.startswith('target:')}
                identity = hashlib.sha256()
                settings = {**target, 'tags': [], 'contexts': {
                    alias: image.config for alias, image in dependencies.items()}}
                identity.update(f'cache-contract={CACHE_CONTRACT}\0'.encode())
                identity.update(json.dumps(settings, sort_keys=True).encode())
                captured = directory / 'contexts' / name / 'main'
                context, dockerfile = paths[name]
                include = captures.get(name) if captures is not None else None
                _capture(repo, context, captured, identity, include)
                captured_contexts = {}
                for alias, value in target.get('contexts', {}).items():
                    if value.startswith('target:'):
                        captured_contexts[alias] = 'docker-image://' + dependencies[alias].reference
                    elif value.startswith('docker-image://'):
                        pinned = _pin_upstream(
                            runtime, value.removeprefix('docker-image://'),
                            refresh=operation == 'refresh', pending=pending_pins,
                        )
                        identity.update(alias.encode() + b'\0' + pinned.encode())
                        captured_contexts[alias] = 'docker-image://' + pinned
                    else:
                        local = (repo / value).resolve(strict=True)
                        captured_local = directory / 'contexts' / name / alias
                        _capture(repo, local, captured_local, identity)
                        captured_contexts[alias] = str(captured_local)
                captured_dockerfile = captured / dockerfile.relative_to(context)
                rewritten = _pin_dockerfile(
                    runtime, captured_dockerfile, target.get('args', {}),
                    set(target.get('contexts', {})), refresh=operation == 'refresh',
                    pending=pending_pins,
                )
                identity.update(hashlib.sha256(rewritten.encode()).digest())
                key = identity.hexdigest()
                tag = 'sandbox-bake:' + key
                try:
                    if operation == 'clean':
                        raise APIError(404, ['clean', tag], 'clean rebuild')
                    images[name] = runtime.resolve_image(tag)
                except APIError as error:
                    if error.status != 404:
                        raise
                    relative_dockerfile = dockerfile.relative_to(context)
                    target.update(context=str(captured), dockerfile=str(captured / relative_dockerfile), tags=[tag],
                                  contexts=captured_contexts,
                                  output=[{'type': 'docker'}])
                    missing[name] = target
                    tags[name] = tag
            if missing:
                with _cache_locks(tag.removeprefix('sandbox-bake:') for tag in tags.values()):
                    for name, tag in list(tags.items()):
                        try:
                            if operation == 'clean':
                                raise APIError(404, ['clean', tag], 'clean rebuild')
                            images[name] = runtime.resolve_image(tag)
                        except APIError as error:
                            if error.status != 404:
                                raise
                        else:
                            missing.pop(name)
                            tags.pop(name)
                    if missing:
                        definition = directory / 'build.json'
                        definition.write_text(json.dumps({'target': missing}))
                        allowed = sorted({
                            value
                            for target in missing.values()
                            for value in [target['context'], *target.get('contexts', {}).values()]
                            if not value.startswith('docker-image://')
                        })
                        with runtime.build_output():
                            result = runtime.run_builder(runtime.argv([
                                'buildx', 'bake', *['--allow=fs.read=' + path for path in allowed],
                                *(['--no-cache'] if operation == 'clean' else []),
                                '--builder', 'default', '--file', str(definition), '--provenance=false', *missing]),
                                cwd=repo, capture=False)
                            if result.returncode:
                                raise BuildError(result.returncode, result.args)
                        resolved = {name: runtime.resolve_image(tag) for name, tag in tags.items()}
                        for name, image in resolved.items():
                            _record(tags[name].removeprefix('sandbox-bake:'), image)
                        images.update(resolved)
            sorter.done(*ready)
        _publish_pins(pending_pins)
        return {name: images[name].reference for name in requested}
