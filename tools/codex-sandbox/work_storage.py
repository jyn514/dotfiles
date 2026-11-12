"""Volume admission and final workspace maintenance shared across sessions.

Short exclusive locks cover container creation and final inspection/maintenance,
not session lifetime. Runtime mounts are the consumer registry, including idle
proxies and containers created before this protocol existed. Never unlink locks.
"""
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid

from workspace_layout import workspace_work_volume, WORK_DIRECTORY


@contextmanager
def volume_admission(workspaces):
    directory = Path.home() / ".cache/codex-sandbox-proxies/work-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ExitStack() as stack:
        for name in sorted({workspace_work_volume(item)[0] for item in workspaces}):
            lock = stack.enter_context((directory / (name + ".lock")).open("a+b"))
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def idle_workspaces(runtime, workspaces):
    """Fail on inspection errors; even a stopped container retains its volume."""
    idle = []
    for workspace in workspaces:
        name, owner = workspace_work_volume(workspace)
        snapshot = json.loads(runtime.run(
            ["volume", "inspect", name], capture_output=True).stdout)[0]
        label = runtime.resource_owner_label("volume")
        if (snapshot.get("Labels") or {}).get(label) != owner:
            raise ValueError(f"work volume ownership changed: {name}")
        consumers = runtime.run(["ps", "--all", "--quiet", "--filter", "volume=" + name],
                                capture_output=True).stdout.strip()
        if not consumers:
            idle.append(workspace)
    return idle


def cleanup_work_storage(runtime, workspaces, image, mount_arguments, scratch):
    """Called after owned services stop; caller retains session recovery state.

    mount_arguments(staging) supplies existing trusted JJ metadata/volume/lock
    mappings. This is an admitted execution runtime, never a recovery-only one.
    """
    with volume_admission(workspaces):
        idle = idle_workspaces(runtime, workspaces)
        if not idle:
            return
        authority = []
        for workspace in idle:
            record = workspace.proxy_authority()
            record["volume"] = str(workspace.guest_root / WORK_DIRECTORY)
            authority.append(record)
        with tempfile.TemporaryDirectory(prefix="work-maintenance-", dir=scratch) as staging:
            temporary = Path(staging) / 'tmp'
            temporary.mkdir(mode=0o700)
            options = ["--network", "none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
                       "--mount", f"type=bind,src={temporary},dst=/tmp",
                       "--entrypoint", "python3", "--workdir", "/tmp",
                       "--env", "JJ_REAL=/opt/agent-tools/libexec/jj",
                       "--env", "XDG_CONFIG_HOME=/tmp/config",
                       "--env", "XDG_CACHE_HOME=/tmp/cache",
                       "--env", "GIT_CONFIG_GLOBAL=/home/codex/.config/git/config",
                       "--mount", f"type=bind,src={Path(__file__).with_name('work_cleanup_guest.py')},dst=/work-cleanup.py,readonly",
                       *mount_arguments(Path(staging))]
            name = "codex-work-cleanup-" + uuid.uuid4().hex[:16]
            with runtime.workload(runtime.inspect_image(image), name, options,
                                  ["/work-cleanup.py", json.dumps(authority)]) as process:
                status = process.wait()
                if status:
                    raise ValueError(f"work cleanup failed (exit {status}); retain session metadata and retry reset")
