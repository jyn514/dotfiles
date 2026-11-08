"""One launch's admitted command-proxy authority and shared-session lifetime.

The launcher owns scheduling: acquire on its signal-owning thread, settle images,
attach, publish, obtain arguments, then release coordination. Joiners and idle
reuse do not replace accepted publication. Join every startup worker before
finish(), and discard the recovery journal only after all launch cleanup succeeds.
The standalone sandbox-proxies CLI remains the routing/recovery entrypoint.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from typing import Any

from proxy_session import SessionLock

HELPER = Path(__file__).with_name("sandbox-proxies.py")
IDLE_SECONDS = 300.0


class SessionError(Exception):
    pass


def _backend(runtime, metadata=None):
    # Each session gets a private namespace: the low-level implementation's
    # runtime and discovered metadata never change while its workers exist.
    spec = importlib.util.spec_from_file_location("sandbox_proxies", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTER_RUNTIME = runtime
    if metadata is not None:
        repository, paths = metadata
        module.use_repository_metadata(repository, paths)
    return module


def runtime_directory(repository: Path, runtime) -> Path:
    """Resolve initialization/reset coordination before a session is admitted."""
    return _backend(runtime).runtime_directory(repository)


class CommandProxySession:
    """Own one immutable runtime/repository binding and its attachment state.

    Inputs are admitted host authority, not guest request fields. Policy and image
    results are boundary values for launcher composition; callers must not mutate
    them in place. No launcher State or callbacks are retained here.
    """

    def __init__(self, runtime, repository: Path, *, container_repository: Path | None = None,
                 uid: int | None = None, gid: int | None = None,
                 workspaces=(), metadata: tuple[Path, Path] | None = None,
                 scratch: Path | None = None) -> None:
        self.runtime = runtime
        self.repository = repository
        self.container_repository = container_repository
        self.uid = uid
        self.gid = gid
        self._workspaces = [workspace.to_dict() for workspace in workspaces] or None
        self._backend = _backend(runtime, (repository, metadata) if metadata is not None else None)
        self._scratch = scratch
        self._directory: Path | None = None
        self._lock: SessionLock | None = None
        self._journal: Path | None = None
        self._state: dict[str, Any] | None = None
        self._policy: dict[str, Any] | None = None
        self._images: dict[str, str] | None = None
        self._reused = False
        self._source_present = False
        self._zuliprc: Path | None = None

    @contextmanager
    def _errors(self):
        try:
            yield
        except (self._backend.ConfigError, ValueError, OSError, subprocess.SubprocessError) as error:
            raise SessionError(str(error)) from error

    @property
    def policy(self) -> dict[str, Any]:
        if self._policy is None:
            raise SessionError("command-proxy policy has not been prepared")
        return self._policy

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(name for name, selected in self.policy.get("capabilities", {}).items() if selected)

    @property
    def zuliprc(self) -> Path | None:
        return self._zuliprc

    @property
    def directory(self) -> Path:
        if self._directory is None:
            self._directory = self._backend.runtime_directory(self.repository)
        return self._directory

    @property
    def recovery_path(self) -> Path | None:
        """Journal reference for combined launch recovery, not API transport."""
        return self._journal

    @property
    def shared(self) -> bool:
        if self._lock is None:
            raise SessionError("command-proxy session lock has not been acquired")
        return self._lock.shared

    def acquire(self) -> None:
        """Acquire on the signal-owning thread; cancellation may interrupt waiting."""
        descriptor, name = tempfile.mkstemp(dir=self._scratch)
        os.close(descriptor)
        self._journal = Path(name)
        self._lock = SessionLock(self.directory)

    def snapshot(self, *, jj_image_command: Path, zulip_image_command: Path,
                 zuliprc: Path) -> dict[str, Any]:
        with self._errors():
            credentials = zuliprc if zuliprc.exists() or zuliprc.is_symlink() else None
            self._source_present = any((self.repository / relative).is_file() for relative in (
                ".agents/sandbox/proxy-commands.json", ".agents/sandbox/docker-bake.hcl"))
            policy = self._backend.snapshot_policy(
                self.repository, jj_image_command=jj_image_command,
                zulip_image_command=zulip_image_command if credentials is not None else None,
                zuliprc=credentials)
            self._policy = policy
            self._zuliprc = credentials if "zulip" in policy["commands"] else None
            return policy

    def bind_policy(self) -> None:
        with self._errors():
            self._backend.bind_manifest(self.repository, self.policy, self.runtime)

    def _request(self, **values):
        return self._backend.SessionRequest(
            repo=self.repository, container_repo=str(self.container_repository),
            uid=self.uid, gid=self.gid, workspaces=self._workspaces,
            state=self._journal, shared=self.shared, source_present=self._source_present,
            zuliprc=self._zuliprc, **values)

    def join(self) -> dict[str, Any]:
        """Accept the locked session's policy/images without reading current policy."""
        with self._errors():
            self._state, accepted = self._backend.join_session(self._request())
            self._policy = accepted["manifest"]
            self._images = accepted["images"]["proxies"]
            self._source_present = accepted["source-present"]
            return accepted

    def attach(self, *, prefix: str, network: str, agent_image: str,
               helper_image: str, images: dict[str, str] | None = None) -> None:
        """Attach settled images; retain journal authority even if startup fails."""
        with self._errors():
            if images is not None:
                self._images = images
            self._state, self._policy, self._reused = self._backend.attach_session(
                self._request(prefix=prefix, network=network, agent_image=agent_image,
                              helper_image=helper_image or None), self.policy, self._images)

    def publish(self) -> None:
        """Validate/replace fresh authority before coordination is released."""
        with self._errors():
            if not self.shared and not self._reused:
                self._backend.publish_session(self.repository, str(self.container_repository),
                                              self._state, self.policy)

    def agent_arguments(self) -> list[str]:
        with self._errors():
            return self._backend.agent_arguments(self.repository, str(self.container_repository),
                                                 self.policy, self._state)

    def release_coordination(self) -> None:
        self._lock.release_coordination()

    def resolve_images(self) -> dict[str, str]:
        """Prepare legacy proxy images for /cd without attachment or publication."""
        with self._errors():
            return self._backend.resolve_images(self.repository, self.policy)

    def reset(self, *, wait: bool = False) -> None:
        with self._errors():
            self._backend.reset_repository(self.repository, wait=wait)

    def _defer_cleanup(self) -> bool:
        lease = secrets.token_hex(16)
        lease_path = self.directory / "idle-cleanup.lease"
        self._backend.write_atomic(lease_path, lease)
        os.chmod(lease_path, 0o600)
        try:
            subprocess.Popen(
                [str(HELPER), "idle-cleanup", "--repo", str(self.repository),
                 "--delay", str(IDLE_SECONDS), "--lease", lease],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True)
        except OSError:
            try:
                if lease_path.read_text(encoding="utf-8") == lease:
                    lease_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def finish(self, *, completed_successfully: bool) -> None:
        """Release lifetime, then exclusively defer/recover after workers join."""
        if self._lock is None:
            return
        unpublished = self._journal if self._lock.coordination is not None else None
        with self._errors():
            if unpublished is None and completed_successfully:
                self._lock.finish(lambda: self._backend.reset_session(self.directory),
                                  defer=self._defer_cleanup)
            else:
                self._lock.finish(lambda: self._backend.reset_session(
                    self.directory, unpublished_state=unpublished))

    def discard_staging(self) -> None:
        """Remove the journal only after caller-confirmed successful cleanup."""
        if self._journal is not None:
            self._journal.unlink(missing_ok=True)
