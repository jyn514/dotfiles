"""Bake declarations for helpers owned by the installed launcher."""

import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    str(ROOT / 'tools/codex-sandbox/auth-proxy/image'): 'auth',
    str(ROOT / '.agents/sandbox/jj-proxy-image'): 'jj',
    str(ROOT / '.agents/sandbox/zulip-proxy-image'): 'zulip',
}
AGENT_CACHE_CONTRACT = 2
DEFAULT_BASE = "node:24-alpine3.22"


def dockerfile_sources(root, dockerfile):
    """Return the local files named by non-stage COPY instructions."""
    sources = [dockerfile]
    for line in (root / dockerfile).read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0] != "COPY" or any(
            field.startswith("--from=") for field in fields[1:-1]
        ):
            continue
        sources.extend(
            Path(field) for field in fields[1:-1] if not field.startswith(("--", "<<"))
        )
    files = []
    for source in sources:
        absolute = root / source
        if absolute.is_dir():
            files.extend(
                path.relative_to(root) for path in absolute.rglob("*")
                if stat.S_ISREG(path.lstat().st_mode)
            )
        elif absolute.is_file():
            files.append(source)
    ordered = sorted(set(files), key=lambda path: os.fsencode(path.as_posix()))
    return [dockerfile, *[path for path in ordered if path != dockerfile]]


def agent_sources(root=ROOT):
    return dockerfile_sources(root, Path("tools/codex-sandbox/image/Dockerfile"))


def installed_pi_revision():
    """Read the commit recorded by the successful host Pi installation."""
    marker = Path.home() / '.local/share/pi/node/.source-revision'
    try:
        revision = marker.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError) as error:
        raise ValueError(
            f'Cannot read installed Pi revision at {marker}; run mise run pi-install: {error}'
        ) from error
    if re.fullmatch(r'[0-9a-f]{40}', revision) is None:
        raise ValueError(
            f'Invalid installed Pi revision at {marker}; run mise run pi-install'
        )
    return revision


def check_agent_pi_revision(runtime, reference):
    """Reject shared images built from a different or unknown host Pi commit."""
    expected = installed_pi_revision()
    result = runtime.run([
        'image', 'inspect', '--format', '{{ index .Config.Labels "dev.codex.pi-revision" }}',
        reference,
    ], capture_output=True)
    if result.stdout.strip() != expected:
        raise ValueError(
            'Shared sandbox image uses a different or unknown Pi revision; '
            'run codex-sandbox restart-all to rebuild for the installed host Pi'
        )


def agent_cache_key(uid, gid, platform, base, pi_revision, *, root=None):
    root = ROOT if root is None else root
    identity = hashlib.sha256()
    identity.update(f"agent-cache-contract={AGENT_CACHE_CONTRACT}\0".encode())
    identity.update(f"uid={uid}\0gid={gid}\0platform={platform}\0".encode())
    identity.update(f"pi-revision={pi_revision}\0".encode())
    identity.update(
        f"base={base.content}\0{base.config}\0{base.rootfs}\0".encode()
    )
    sources = agent_sources() if root == ROOT else agent_sources(root)
    for path in sources:
        data = (root / path).read_bytes()
        identity.update(os.fsencode(path.as_posix()) + b"\0")
        identity.update(hashlib.sha256(data).digest())
    return identity.hexdigest()


def resolve_agent(runtime, uid, gid, base_reference, *, operation="resolve"):
    if operation not in {"resolve", "refresh", "clean"}:
        raise ValueError(f"unsupported agent image operation: {operation}")
    from bake import _capture, _pin_dockerfile
    # Capture once so the image identity and build use the same installed commit.
    pi_revision = installed_pi_revision()
    with tempfile.TemporaryDirectory(prefix="sandbox-agent-image-") as directory:
        captured = Path(directory).resolve() / "context"
        _capture(ROOT, ROOT, captured, hashlib.sha256(), agent_sources())
        # The cache key needs local base contents before BuildKit can pull FROM.
        # Only the launcher-owned default may bypass a project image resolver.
        if base_reference == DEFAULT_BASE and runtime.image_if_available(base_reference) is None:
            runtime.run(["pull", base_reference], stdout=sys.stderr)
        base = runtime.inspect_image(base_reference)
        _pin_dockerfile(
            runtime, captured / "tools/codex-sandbox/image/Dockerfile",
            {"BASE_IMAGE": base.reference}, set(), refresh=operation == "refresh",
        )
        tag = "codex-sandbox:" + agent_cache_key(
            uid, gid, runtime.build_platform(), base, pi_revision, root=captured,
        )
        existing = None if operation == "clean" else runtime.image_if_available(tag)
        if existing is not None:
            return existing.reference
        build_options = {"no_cache": True} if operation == "clean" else {}
        return runtime.build(
            tag, captured / "tools/codex-sandbox/image/Dockerfile", captured,
            build_args=[f"AGENT_UID={uid}", f"AGENT_GID={gid}",
                        f"PI_REVISION={pi_revision}", f"BASE_IMAGE={base.reference}"],
            **build_options,
        ).reference


def target(command):
    # Only the exact installed entrypoint is owned. Repository names and target
    # declarations cannot substitute for these helpers.
    return COMMANDS.get(command[0]) if len(command) == 1 else None


def source_paths(requested=('auth', 'jj', 'zulip')):
    sources = {}
    if 'auth' in requested:
        sources['auth'] = ['tools/codex-sandbox/auth-proxy/Dockerfile',
                           'tools/codex-sandbox/auth-proxy/profile_helper.py',
                           'tools/codex-sandbox/auth-proxy/codex_profile.py',
                           'tools/codex-sandbox/auth-proxy/typed_broker.py',
                           'tools/codex-sandbox/gateway.py']
    if 'jj' in requested:
        sources['jj'] = [str(path) for path in dockerfile_sources(
            ROOT, Path('tools/jj-proxy/Dockerfile'),
        )]
    if 'zulip' in requested:
        sources['zulip'] = ['tools/zulip-proxy/Dockerfile', 'tools/zulip-proxy/server.py',
                            'tools/zulip-proxy/forward.py', 'tools/zulip-proxy/protocol.json',
                            'tools/codex-sandbox/auth-proxy/typed_broker.py']
    return sources


def declaration(requested=('auth', 'jj', 'zulip')):
    targets = {}
    for name, paths in source_paths(requested).items():
        key = hashlib.sha256()
        for path in sorted(paths):
            key.update(path.encode() + b'\0')
            key.update(hashlib.sha256((ROOT / path).read_bytes()).digest())
        targets[name] = {'context': '.', 'dockerfile': paths[0],
                         'tags': [f'codex-{name}:{key.hexdigest()}'],
                         'platforms': ['${BUILDPLATFORM}']}
    return {'variable': {'BUILDPLATFORM': {'default': 'linux/arm64'}}, 'target': targets}


if __name__ == '__main__':
    if len(sys.argv) == 1:
        try:
            print(installed_pi_revision())
        except ValueError as error:
            print(error, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    image = declaration([sys.argv[1]])['target'][sys.argv[1]]
    executable = str(ROOT / 'tools/codex-sandbox/sandbox-image')
    os.chdir(ROOT)
    os.execv(executable, [executable, 'build', '--if-missing', '--file',
                         image['dockerfile'], '--tag', image['tags'][0], '.'])
