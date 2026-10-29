"""Trusted, immutable host workspace descriptions and their guest projections.

Import-only internal interface shared by the launcher and proxy manager. Discovery
never initializes a repository; the launcher owns initialization, publication and
temporary files. Native metadata queries ignore working-copy snapshotting.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import subprocess


class WorkspaceError(ValueError):
    pass


def _safe_path(path: Path) -> Path:
    if not path.is_absolute() or str(path).startswith("//") or ".." in path.parts or any(c in str(path) for c in (",", "\0", "\n", "\r")):
        raise WorkspaceError(f"Unsafe workspace mount path: {path}")
    return path


@dataclass(frozen=True)
class WorkspaceLayout:
    host_root: Path
    guest_root: Path
    git_dir: Path
    common_dir: Path
    jj_repo: Path
    lock_file: Path

    def __post_init__(self):
        for path in (self.host_root, self.guest_root, self.git_dir,
                     self.common_dir, self.jj_repo, self.lock_file):
            _safe_path(path)
        if self.guest_root == Path("/src") or not self.guest_root.is_relative_to("/src"):
            raise WorkspaceError(f"Workspace guest root must be below /src: {self.guest_root}")

    def to_dict(self) -> dict[str, str]:
        return {key: str(getattr(self, key)) for key in (
            "host_root", "guest_root", "git_dir", "common_dir", "jj_repo", "lock_file")}

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> "WorkspaceLayout":
        keys = {"host_root", "guest_root", "git_dir", "common_dir", "jj_repo", "lock_file"}
        if not isinstance(value, dict) or set(value) != keys or any(
                not isinstance(item, str) for item in value.values()):
            raise WorkspaceError("Invalid workspace description")
        return cls(**{key: Path(item) for key, item in value.items()})

    def guest_path(self, path: Path) -> Path:
        """Preserve relative metadata pointers when moving the workspace root."""
        return Path(os.path.normpath(self.guest_root / os.path.relpath(path, self.host_root)))

    def proxy_authority(self) -> dict[str, str]:
        return {"root": str(self.guest_root), "git_dir": str(self.guest_path(self.git_dir)),
                "common_dir": str(self.guest_path(self.common_dir)),
                "jj_repo": str(self.guest_path(self.jj_repo)),
                "lock": str(Path("/run/jj-locks") / self.lock_file.name)}

    def metadata_mounts(self) -> list[tuple[Path, Path]]:
        entry = self.host_root / ".git"
        # A gitfile must remain a file; JJ-only workspaces have no .git
        # entry and need the backing directory overlay instead. Non-strict
        # inspection keeps stale descriptions usable for cleanup.
        mounts = [(entry if entry.is_file() else self.git_dir, self.guest_root / ".git"),
                  (self.host_root / ".jj", self.guest_root / ".jj")]
        for path in dict.fromkeys((self.git_dir, self.common_dir, self.jj_repo)):
            mounts.append((path, self.guest_path(path)))
            if not path.is_relative_to(self.host_root):
                # Absolute pointers and relative pointers must both retain their
                # native meaning, including linked Git worktree back-pointers.
                mounts.append((path, path))
        unique = list(dict.fromkeys(mounts))
        return [(source, target) for source, target in unique if not any(
            source != parent_source and source.is_relative_to(parent_source)
            and target == parent_target / source.relative_to(parent_source)
            for parent_source, parent_target in unique)]

    def repository_aliases(self) -> list[Path]:
        aliases = []
        for path in (self.git_dir, self.common_dir):
            if not path.is_relative_to(self.host_root):
                for target in (path, self.guest_path(path)):
                    alias = Path(os.path.normpath(target / os.path.relpath(self.host_root, path)))
                    if alias in (Path("/"), Path("/src")):
                        raise WorkspaceError(f"Metadata produced an unsafe worktree alias: {alias}")
                    if alias != self.guest_root:
                        aliases.append(alias)
        return list(dict.fromkeys(aliases))


@dataclass(frozen=True)
class RepositoryMetadata:
    host_root: Path
    git_dir: Path
    common_dir: Path
    jj_repo: Path


def jj_repository_path(host_root: Path) -> Path:
    """Resolve the native JJ store pointer without snapshotting or rewriting it."""
    entry = host_root / ".jj/repo"
    if entry.is_file() and not entry.is_symlink():
        if entry.stat().st_nlink != 1:
            raise WorkspaceError("Jujutsu repository pointer must not be hard linked")
        value = entry.read_text(encoding="utf-8").strip()
        if not value or any(c in value for c in ("\0", "\n", "\r")):
            raise WorkspaceError("Jujutsu repository pointer is invalid")
        target = Path(value)
        if not target.is_absolute():
            target = entry.parent / target
        backing = target.resolve(strict=True)
    else:
        backing = entry.resolve(strict=True)
    if not backing.is_dir():
        raise WorkspaceError(f"Jujutsu repository metadata is invalid: {backing}")
    return backing


def discover_repository_metadata(host_root: Path, *, runner=None) -> RepositoryMetadata:
    """Validate only existing native metadata, without launch authority/effects.

    runner has the launcher's run(arguments, capture=True, cwd=Path) signature.
    Native JJ queries ignore working-copy snapshotting.
    """
    if runner is None:
        def runner(arguments, *, capture, cwd=None):
            return subprocess.run(arguments, check=True, text=True, capture_output=capture, cwd=cwd)
    try:
        root = host_root.resolve(strict=True)
        jj = root / ".jj"
        if not jj.is_dir() or jj.is_symlink():
            raise WorkspaceError(f"Invalid Jujutsu workspace metadata: {jj}")
        git = Path(runner(["jj", "git", "root", "--ignore-working-copy"],
                          capture=True, cwd=root).stdout.strip()).resolve(strict=True)
        git_context = root if (root / ".git").exists() else git
        # -C does not override these inherited selectors. Authority belongs to
        # host_root, not a caller's Git shell context; keep native linked-worktree
        # discovery and the runner's process/stdio contract unchanged.
        lines = runner(["env", "-u", "GIT_DIR", "-u", "GIT_COMMON_DIR",
                        "git", "-C", str(git_context), "rev-parse", "--path-format=absolute",
                        "--git-dir", "--git-common-dir"], capture=True).stdout.splitlines()
        if len(lines) != 2:
            raise WorkspaceError("Git returned an invalid metadata layout")
        git_dir, common_dir = (Path(line).resolve(strict=True) for line in lines)
        jj_repo = jj_repository_path(root)
        for path in (git_dir, common_dir, jj_repo):
            if not path.is_dir():
                raise WorkspaceError(f"Repository metadata directory is invalid: {path}")
        return RepositoryMetadata(root, git_dir, common_dir, jj_repo)
    except WorkspaceError as error:
        raise WorkspaceError(f"Invalid repository layout for {host_root}: {error}") from error
    except (OSError, UnicodeError, subprocess.CalledProcessError) as error:
        raise WorkspaceError(f"Cannot resolve repository metadata for {host_root}: {error}") from error


def discover_workspace(host_root: Path, guest_root: Path, home: Path, *, runner=None) -> WorkspaceLayout:
    """Derive launch authority after validating native repository metadata.

    Persistent locks are created separately, after all workspaces validate.
    """
    metadata = discover_repository_metadata(host_root, runner=runner)
    digest = hashlib.sha256(os.fsencode(metadata.jj_repo)).hexdigest()
    return WorkspaceLayout(metadata.host_root, guest_root, metadata.git_dir, metadata.common_dir,
                           metadata.jj_repo,
                           home / ".cache/codex-sandbox-proxies/request-locks" / f"{digest}.lock")


def ensure_request_lock(layout: WorkspaceLayout) -> None:
    """Never unlink or replace an inode another trusted service may be locking."""
    directory = layout.lock_file.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise WorkspaceError(f"Unsafe request-lock directory: {directory}")
    fd = os.open(layout.lock_file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise WorkspaceError(f"Unsafe repository request lock: {layout.lock_file}")
    finally:
        os.close(fd)


def workspace_guest_root(home: Path, active_host: Path, active_guest: Path, dotfiles: Path,
                         *, reserved: list[tuple[Path, Path]] | None = None) -> Path:
    """Keep the active mapping; prefer the existing source view for dotfiles."""
    if dotfiles == active_host:
        return active_guest
    source = (home / "src").resolve(strict=True)

    def collides(candidate):
        if candidate.is_relative_to(active_guest) or active_guest.is_relative_to(candidate):
            return True
        for host, guest in reserved or []:
            if guest.is_relative_to(candidate):
                if host != dotfiles / guest.relative_to(candidate):
                    return True
            elif candidate.is_relative_to(guest):
                return True
        return False

    if dotfiles.is_relative_to(source) and dotfiles != source:
        natural = Path("/src") / dotfiles.relative_to(source)
        if not collides(natural):
            return natural
    candidate = Path("/src/dotfiles")
    suffix = 0
    while ((source / candidate.relative_to("/src")).exists()
           or (source / candidate.relative_to("/src")).is_symlink()
           or collides(candidate)):
        suffix += 1
        candidate = Path(f"/src/dotfiles-{suffix}")
    return candidate
