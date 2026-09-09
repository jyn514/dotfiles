"""Compose repository Bake targets and trusted launcher images into one build."""

import hashlib
import json


class BuildBatch:
    def __init__(self, runtime, repository):
        self.runtime = runtime
        self.repository = repository
        self.targets = {}

    def repository_targets(self, names):
        if not names:
            return
        definition = self.repository / '.agents/sandbox/docker-bake.hcl'
        if not definition.is_file():
            raise ValueError(f'{definition} is required; define the requested Bake targets: {", ".join(names)}')
        targets = self.runtime.bake_targets(definition, names, cwd=self.repository)
        for name, target in targets.items():
            # Repository names cannot overwrite trusted launcher targets.
            target = {**target, 'contexts': {
                key: 'target:repo-' + value.removeprefix('target:') if value.startswith('target:') else value
                for key, value in target.get('contexts', {}).items()}}
            self.add('repo-' + name, target)

    def add(self, name, target):
        if name in self.targets:
            raise ValueError(f'duplicate build target: {name}')
        # Stable private tags avoid collisions between repositories and agent
        # configurations. BuildKit, not tag existence, decides cache validity.
        identity = json.dumps([str(self.repository), name, target], sort_keys=True)
        tag = 'codex-sandbox-bake:' + hashlib.sha256(identity.encode()).hexdigest()
        self.targets[name] = {**target, 'tags': [tag], 'output': [{'type': 'docker'}], 'cache-to': []}
        return name

    def finish(self):
        if not self.targets:
            return {}
        metadata = self.runtime.bake(self.targets, cwd=self.repository)
        images = {}
        for name, target in self.targets.items():
            image = self.runtime.inspect_image(target['tags'][0])
            if image.content != metadata[name]['containerimage.digest']:
                raise ValueError('image tag differs from the completed Bake result')
            images[name] = image
        return images


def trusted_target(dotfiles, dockerfile):
    return {'context': str(dotfiles), 'dockerfile': str(dotfiles / dockerfile)}


def collect_proxies(batch, manifest, dotfiles):
    proxies = {}
    requested = []
    for name, command in manifest['commands'].items():
        builder = command.get('image-command')
        if builder == [str(dotfiles / '.agents/sandbox/jj-proxy-image')]:
            proxies[name] = batch.add('trusted-jj', trusted_target(dotfiles, 'tools/jj-proxy/Dockerfile'))
        elif builder == [str(dotfiles / '.agents/sandbox/zulip-proxy-image')]:
            proxies[name] = batch.add('trusted-zulip', trusted_target(dotfiles, 'tools/zulip-proxy/Dockerfile'))
        else:
            target = command.get('image-target')
            if not target:
                raise ValueError(f'proxy {name} requires image-target naming a repository Bake target for lima-docker')
            requested.append(target)
            proxies[name] = 'repo-' + target
    return proxies, requested


def prepare_proxies(runtime, repository, manifest, dotfiles):
    batch = BuildBatch(runtime, repository)
    proxies, requested = collect_proxies(batch, manifest, dotfiles)
    batch.repository_targets(list(dict.fromkeys(requested)))
    images = batch.finish()
    return {name: images[target].reference for name, target in proxies.items()}


def prepare_launch(runtime, state, dotfiles):
    batch = BuildBatch(runtime, state.repository)
    manifest = json.loads(state.manifest.read_text())
    proxies, requested = collect_proxies(batch, manifest, dotfiles)
    has_base = (state.repository / '.agents/sandbox/docker-bake.hcl').is_file()
    if not has_base and (state.repository / '.agents/sandbox/base-image').exists():
        raise ValueError('lima-docker requires .agents/sandbox/docker-bake.hcl with a base target; migrate base-image')
    batch.repository_targets(list(dict.fromkeys((['base'] if has_base else []) + requested)))
    auth = batch.add('trusted-auth', trusted_target(dotfiles, 'tools/codex-sandbox/auth-proxy/Dockerfile'))
    agent = trusted_target(dotfiles, 'tools/codex-sandbox/image/Dockerfile')
    agent['args'] = {'AGENT_UID': str(state.uid), 'AGENT_GID': str(state.gid), 'TERM': state.term,
                     'BASE_IMAGE': 'sandbox-base' if has_base else 'node:24-alpine3.22'}
    if has_base:
        agent['contexts'] = {'sandbox-base': 'target:repo-base'}
    batch.add('trusted-agent', agent)
    images = batch.finish()
    return images['trusted-agent'].reference, images[auth].reference, {
        name: images[target].reference for name, target in proxies.items()}
