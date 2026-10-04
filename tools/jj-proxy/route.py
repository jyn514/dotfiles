#!/usr/bin/env python3
"""Read-only JJ dispatch planning. Import route(), or invoke route.py -- JJ_ARG... .

This is routing evidence, not authorization. Unknown storage is native; JJ and
protective mounts remain responsible for validation and access control.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import urlsplit


class RouteError(ValueError):
    pass


def physical(path, cwd):
    path = Path(path)
    return (path if path.is_absolute() else cwd / path).resolve()


def within(path, root):
    return path == root or root in path.parents


@dataclass(frozen=True)
class Mount:
    id: int
    parent: int
    device: str
    root: Path
    point: Path
    fs: str
    source: str

    def backing(self, path):
        return self.root / path.relative_to(self.point)

    @property
    def identity(self):
        return self.device, self.fs


def parse_mountinfo(text):
    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)
    mounts = []
    for line in text.splitlines():
        before, sep, after = line.partition(" - ")
        fields, tail = before.split(), after.split()
        if not sep or len(fields) < 6 or len(tail) < 3:
            raise RouteError("malformed mountinfo")
        mounts.append(Mount(int(fields[0]), int(fields[1]), fields[2],
                            Path(unescape(fields[3])), Path(unescape(fields[4])),
                            tail[0], unescape(tail[1])))
    return mounts


def effective_mount(path, mounts):
    """Walk visible mount children, not hidden descendants of a covered mount."""
    roots = [m for m in mounts if m.point == Path('/')]
    if not roots:
        return None
    current = roots[-1]
    visited = set()
    while current.id not in visited:
        visited.add(current.id)
        children = [m for m in mounts if m.parent == current.id
                    and within(path, m.point) and m.id not in visited]
        if not children:
            return current
        depth = min(len(m.point.parts) for m in children)
        # IDs can be recycled; mountinfo traversal order and parent links,
        # not numerical IDs, describe stacking.
        current = [m for m in children if len(m.point.parts) == depth][-1]
    return current


def global_config(env, cwd):
    """Read only native global configuration; never repository or command config."""
    if 'JJ_CONFIG' in env:
        paths = [Path(p) for p in env['JJ_CONFIG'].split(os.pathsep) if p]
    else:
        home = Path(env.get('HOME', str(Path.home())))
        paths = [home / '.jjconfig.toml',
                 Path(env.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'jj/config.toml',
                 Path(env.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'jj/conf.d']
    config = {}
    valid = True
    for path in paths:
        try:
            path = physical(path, cwd)
            files = sorted(p for p in path.iterdir() if p.suffix == '.toml') if path.is_dir() else [path]
            for file in files:
                if file.is_file():
                    with file.open('rb') as stream:
                        data = tomllib.load(stream)
                    for section in ('aliases', 'ui', 'git'):
                        if isinstance(data.get(section), dict):
                            config.setdefault(section, {}).update(data[section])
        except (OSError, ValueError):
            valid = False
    return config, valid


# Values must be consumed before interpreting global selectors. This is not a
# command allowlist: unrecognized commands still reach JJ unchanged.
GLOBAL_VALUES = {'-R', '--repository', '--at-operation', '--at-op', '-@',
                 '--color', '--config', '--config-file'}
OPERAND_VALUES = {'-m', '--message', '-r', '--revision', '--revisions', '-T',
                  '--template', '--tool', '--from', '--to', '--onto', '--insert-after',
                  '--insert-before', '--destination', '-d', '--source', '-s',
                  '--git-repo', '--remote', '--depth', '--fetch-tags', '-b', '--branch', '--bookmark', '-t', '--tag',
                  '--name', '--author', '--limit', '-n'}
# Short names are command-specific in the installed CLI. These boolean uses
# must not consume a following selector/no-working-copy flag as their operand.
# Audited against native JJ b8f7c455 help, including all 117 command prefixes.
BOOLEAN_OPERAND_OPTIONS = {
    ('diff',): {'-b', '-s'},
    ('interdiff',): {'-b', '-s'},
    ('show',): {'-b', '-s'},
    ('evolog',): {'-s'},
    ('evolution-log',): {'-s'},
    ('log',): {'-s'},
    ('next',): {'-n'},
    ('prev',): {'-n'},
    ('gerrit', 'upload'): {'-n'},
    ('bookmark', 'list'): {'-t'},
    ('operation', 'diff'): {'-s'},
    ('operation', 'log'): {'-d', '-s'},
    ('operation', 'show'): {'-s'},
    ('op', 'diff'): {'-s'},
    ('op', 'log'): {'-d', '-s'},
    ('op', 'show'): {'-s'},
}
GLOBAL_FLAGS = {'--ignore-working-copy', '--no-integrate-operation', '--ignore-immutable',
                '--debug', '--quiet', '-q', '--no-pager', '-h', '--help', '-V', '--version'}


@dataclass
class Invocation:
    command: list[str]
    operands: list[str]
    selector: str | None
    hooks: bool
    git_repo: str | None
    valid: bool
    colocate: bool = True


def invocation(argv, config, config_valid=True):
    tokens = list(argv)
    if not tokens:
        default = config.get('ui', {}).get('default-command', 'log')
        if isinstance(default, str):
            tokens = [default]
        elif isinstance(default, list) and default and all(isinstance(v, str) for v in default):
            tokens = list(default)
        else:
            return Invocation([], [], None, False, None, False)
    aliases = config.get('aliases', {})
    expanded = set()
    selector = git_repo = None
    hooks = config_valid
    valid = True
    colocate = config.get('git', {}).get('colocate', True) is not False
    command, operands = [], []
    options = True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Clap permits short flag clusters, including command-specific flags.
        boolean_options = BOOLEAN_OPERAND_OPTIONS.get(tuple(command), set())
        if options and len(token) > 2 and token.startswith('-') and not token.startswith('--') and (token[1] in 'qhV' or token[:2] in boolean_options):
            tokens[i:i + 1] = ['-' + token[1], '-' + token[2:]]
            continue
        if options and token == '--':
            options = False
            i += 1
            continue
        key, equals, value = token.partition('=')
        attached = False
        if options and token.startswith('-R') and token != '-R':
            key, value, attached = '-R', token[2:], True
        elif options and len(token) > 2 and token[:2] in {'-@', '-m', '-r', '-T', '-b', '-t', '-d', '-s', '-n'}:
            key, value, attached = token[:2], token[2:], True
        if options and (key in GLOBAL_VALUES or key in OPERAND_VALUES and key not in boolean_options):
            if not equals and not attached:
                i += 1
                if i == len(tokens):
                    if key in GLOBAL_VALUES:
                        raise RouteError(f"{key} requires a value")
                    valid = hooks = False
                    break
                value = tokens[i]
            if key in {'-R', '--repository'}:
                if not value or selector is not None:
                    raise RouteError('invalid or repeated repository selector')
                selector = value
            elif key in {'-@', '--at-op', '--at-operation'}:
                hooks = False
            elif key == '--git-repo':
                git_repo = value
            i += 1
            continue
        if options and token.startswith('-'):
            if token == '--no-colocate':
                colocate = False
            elif token == '--colocate':
                colocate = True
            if token in {'--ignore-working-copy', '--no-integrate-operation', '-h', '--help', '-V', '--version'}:
                hooks = False
            if not command and token not in GLOBAL_FLAGS:
                valid = False
            i += 1
            continue
        if not command:
            if token in aliases:
                expansion = aliases[token]
                if token in expanded or not isinstance(expansion, list) or not expansion or not all(isinstance(v, str) for v in expansion):
                    valid = hooks = False
                else:
                    expanded.add(token)
                    tokens[i:i + 1] = expansion
                    continue
            command.append(token)
            if token in {'help', 'version'}:
                hooks = False
        elif len(command) == 1 and command[0] in {'git', 'gerrit', 'workspace', 'operation', 'op', 'file', 'bookmark', 'config', 'util'}:
            command.append(token)
        else:
            operands.append(token)
        i += 1
    if not command:
        default = config.get('ui', {}).get('default-command', 'log')
        if isinstance(default, str) and default and not default.startswith('-'):
            return invocation([default] + tokens, config, config_valid) if tokens else Invocation([default], [], selector, hooks, git_repo, valid)
        valid = hooks = False
    return Invocation(command, operands, selector, hooks, git_repo, valid, colocate)


def git_metadata(path, *, discover=False):
    """Resolve a known Git target, gitfile, and optional common directory.

    Only explicit bootstrap --git-repo inputs use worktree-root discovery.
    A store/git_target already names the backing: its .git child is unrelated.
    """
    paths = []
    valid = True
    try:
        path = path.resolve()
        if discover and path.is_dir() and (path / '.git').exists():
            path = (path / '.git').resolve()
        paths.append(path)
        if path.is_file():
            text = path.read_text().strip()
            if not text.startswith('gitdir: ') or not text[8:].strip():
                return paths, False
            path = physical(text[8:].strip(), path.parent)
            paths.append(path)
        if not path.is_dir():
            return paths, False
        common = path / 'commondir'
        if common.exists():
            text = common.read_text().strip()
            if not text:
                return paths, False
            common_path = physical(text, path)
            paths.append(common_path)
            valid = common_path.is_dir() and (common_path / 'objects').is_dir() and (path / 'HEAD').is_file()
        else:
            valid = (path / 'HEAD').is_file() and (path / 'objects').is_dir()
    except (OSError, ValueError, RuntimeError):
        valid = False
    return paths, valid


def metadata(workspace):
    paths = [workspace, workspace / '.jj', workspace / '.jj/working_copy']
    valid = True
    try:
        pointer = workspace / '.jj/repo'
        paths.append(pointer.resolve())
        if pointer.is_file():
            text = os.fsdecode(pointer.read_bytes())
            if not text:
                return paths, False
            repo = physical(text, pointer.parent)
        else:
            repo = pointer.resolve()
        paths.append(repo)
        # These are the standard JJ mutable stores, also for non-Git backends.
        valid = repo.is_dir() and (workspace / '.jj/working_copy').is_dir() and all(
            (repo / name).is_dir() for name in ('store', 'op_store', 'op_heads'))
        paths += [repo / name for name in ('store', 'op_store', 'op_heads', 'index',
                                          'workspace_store', 'submodule_store')]
        store_type = (repo / 'store/type').read_text() if (repo / 'store/type').is_file() else None
        valid = valid and store_type in {'git', 'local'}
        target = repo / 'store/git_target'
        if store_type == 'git' and not target.is_file():
            valid = False
        if store_type == 'git' and target.exists():
            text = os.fsdecode(target.read_bytes())
            if not text:
                return paths, False
            git_paths, git_valid = git_metadata(physical(text, target.parent))
            paths += git_paths
            valid = valid and git_valid
        paths = [p.resolve() for p in paths]
    except (OSError, ValueError, RuntimeError):
        valid = False
    return paths, valid


def workspace_at(path, explicit=False):
    if not path.is_dir():
        return None
    for ancestor in [path, *path.parents]:
        if (ancestor / '.jj').exists():
            return ancestor
        if explicit:
            break
    return None


def clone_destination(source, cwd):
    # Match clone_destination_for_source() after absolute_git_url() in native
    # jj b8f7c455: strip .git, strip ONE trailing /, then last /, backslash, :.
    # Local sources (including symlinks and file URLs) are canonicalized by
    # gix before JJ derives the destination, not just made absolute.
    if source.startswith('file://'):
        source = str(physical(urlsplit(source).path, cwd))
    elif not re.match(r'^[^/]*:', source):
        source = str(physical(source, cwd))
    if source.endswith('.git'):
        source = source[:-4]
    if source.endswith('/'):
        source = source[:-1]
    parts = re.split(r'[/\\:]', source)
    return parts[-1] if len(parts) > 1 else None


def host_regions(env, mounts, cwd):
    anchors = []
    source = Path('/src').resolve()
    mount = effective_mount(source, mounts)
    if mount and mount.point == source:
        anchors.append((source, False))
    selected = physical(env.get('JJ_PROXY_REPO', '/src/work'), cwd)
    explicit_selected = bool(env.get('JJ_PROXY_REPO'))
    if selected.exists():
        # The launcher's explicit selected-workspace role is host evidence even
        # without a distinct mount. Only its backing SUBREGION is anchored,
        # never the entire rootfs. Effective nested mounts still differ.
        anchors.append((selected, explicit_selected))
        workspace = workspace_at(selected, explicit=True)
        if workspace:
            anchors += [(path, explicit_selected) for path in metadata(workspace)[0][1:]]
    regions = []
    for path, allow_root in anchors:
        mount = effective_mount(path, mounts)
        if mount and (allow_root or mount.point != Path('/')):
            regions.append((mount.identity, mount.backing(path)))
    return regions


def route(argv, *, cwd=None, env=None, mountinfo=None):
    """Return the checked consumer JSON object; no subprocesses or writes.

    mountinfo text is injectable for proven mount fixtures. None reads proc only
    when sandbox routing is enabled. No mount evidence means default native.
    """
    env = dict(os.environ if env is None else env)
    cwd = physical(os.getcwd() if cwd is None else cwd, Path.cwd())
    config, config_valid = global_config(env, cwd)
    call = invocation(argv, config, config_valid)
    selected = physical(call.selector, cwd) if call.selector is not None else cwd
    if call.selector is not None and not selected.is_dir():
        raise RouteError('repository selector is not an existing directory')
    workspace = workspace_at(selected, explicit=call.selector is not None)
    destination = None
    paths = [selected]
    valid = False
    bootstrap = call.command in (['git', 'init'], ['git', 'clone']) and call.valid
    if bootstrap:
        if call.command[-1] == 'init':
            name = call.operands[0] if call.operands else '.'
            valid = len(call.operands) <= 1
        else:
            name = call.operands[1] if len(call.operands) == 2 else clone_destination(call.operands[0], cwd) if call.operands else None
            valid = 1 <= len(call.operands) <= 2 and name is not None
        if name is not None:
            destination = physical(name, cwd)
            paths = [destination, destination / '.jj']
            # Default bootstrap colocation can use an existing .git. Explicit
            # shared backing and --no-colocate cannot mutate that unrelated repo.
            if call.colocate and call.git_repo is None:
                paths.append(destination / '.git')
            if (destination / '.jj').exists():
                existing_paths, existing_valid = metadata(destination)
                paths += existing_paths
                valid = valid and existing_valid
            if call.git_repo is not None:
                backing, backing_valid = git_metadata(physical(call.git_repo, cwd), discover=True)
                paths += backing
                valid = valid and backing_valid
        workspace = None
    elif workspace is not None:
        paths, valid = metadata(workspace)
    backend = 'native'
    if env.get('SANDBOX_PROXY_DIR'):
        if mountinfo is None:
            try:
                mountinfo = Path('/proc/self/mountinfo').read_text()
            except OSError:
                mountinfo = ''
        mounts = parse_mountinfo(mountinfo)
        regions = host_regions(env, mounts, cwd)
        for path in paths:
            path = path.resolve()
            mount = effective_mount(path, mounts)
            if mount and any(mount.identity == identity and within(mount.backing(path), root)
                             for identity, root in regions):
                backend = 'proxy'
                break
    result = {'backend': backend, 'workspace': str(workspace) if workspace else None,
              'destination': str(destination) if destination else None,
              'command': call.command, 'hooks': bool(call.hooks and valid and call.valid)}
    check_result(result)
    return result


def check_result(result):
    if set(result) != {'backend', 'workspace', 'destination', 'command', 'hooks'}:
        raise RouteError('invalid route fields')
    if result['backend'] not in {'native', 'proxy'} or type(result['hooks']) is not bool:
        raise RouteError('invalid route decision')
    if not isinstance(result['command'], list) or not all(isinstance(x, str) for x in result['command']):
        raise RouteError('invalid route command')
    for key in ('workspace', 'destination'):
        value = result[key]
        if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
            raise RouteError(f'invalid route {key}')


def main():
    if sys.argv[1:2] != ['--']:
        raise RouteError('usage: route.py -- JJ_ARG...')
    print(json.dumps(route(sys.argv[2:]), separators=(',', ':')))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f'jj route: {error}', file=sys.stderr)
        raise SystemExit(125)
