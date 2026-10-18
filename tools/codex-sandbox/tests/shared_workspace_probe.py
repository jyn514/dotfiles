"""Two real JJ services share authority and serialize attribution across containers.

Imported by image_runtime_integration.py; fixture sources are copied into a private
engine volume because the Docker daemon need not share this process's filesystem.
"""
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tarfile
import tempfile
import time
from unittest import mock
import uuid


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[2]


def fixture_commit_revision(description: str) -> str:
    # JJ appends a newline to commit messages. Do not rely on the default
    # string-pattern kind matching a message without that newline.
    return f"description(substring:{json.dumps(description)})"


def fixture_jj_container(volume: str, root: Path, cwd: Path) -> list[str]:
    """Keep native fixture generation and discovery on the consuming JJ version."""
    return ["docker", "run", "--rm", "--network", "none", "--user", "65532:65532",
            "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp:mode=1777",
            "--mount", f"type=volume,src={volume},dst={root}",
            "--workdir", str(cwd), "--env", "HOME=/nonexistent",
            "--env", "XDG_CONFIG_HOME=/tmp/jj-fixture-config"]


def initialize_fixture_metadata(run, image: str, volume: str, root: Path, *, linked: bool) -> None:
    # The original root mount preserves absolute linked-workspace pointers.
    # Never initialize or migrate inspection targets through the proxy.
    setup = DIRECTORY / "fixtures/shared-workspace-setup.sh"
    run(*fixture_jj_container(volume, root, root), "--interactive",
        "--entrypoint", "/trusted/bin/sh", image, "-s", "--", str(root),
        "linked" if linked else "ordinary", input=setup.read_text())


def probe_shared_workspaces(image: str, *, linked: bool = False) -> None:
    from docker_runtime import Docker
    from workspace_layout import discover_workspace, ensure_request_lock

    module = runpy.run_path(str(DIRECTORY.parent / "sandbox-proxies.py"))
    launcher = runpy.run_path(str(DIRECTORY.parent / "codex-sandbox"))
    prefix = "jj-workspaces-" + uuid.uuid4().hex[:12]
    volume = prefix + "-fixture"
    services = [prefix + "-a", prefix + "-b"]
    containers = []
    volumes = []
    clients = []

    def run(*args, check=True, input=None, cwd=ROOT):
        result = subprocess.run([str(arg) for arg in args], cwd=cwd, text=True, input=input,
                                capture_output=True)
        if check and result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
        return result

    def marker(service, name):
        return run("docker", "exec", service, "/trusted/bin/busybox", "test", "-f",
                   "/run/sandbox-proxy/" + name, check=False).returncode == 0

    def wait_marker(service, name, process):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if marker(service, name):
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"request exited before {name}: {stdout}\n{stderr}")
            time.sleep(0.05)
        raise RuntimeError(f"timed out waiting for {name}")

    def request(service, identity, *argv):
        process = subprocess.Popen([
            "docker", "exec", "--workdir", "/src/project", "--env", "JJ_USER=" + identity,
            "--env", "JJ_EMAIL=" + identity.lower() + "@example.test", service,
            "/trusted/bin/jj-proxy", *argv,
        ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        clients.append(process)
        return process

    def finish(process):
        stdout, stderr = process.communicate(timeout=40)
        if process.returncode:
            raise RuntimeError(f"workspace request failed: {stdout}\n{stderr}")
        return stdout

    def query(service, repo, revision, template):
        return run("docker", "exec", "--workdir", "/src/project", "--env", "JJ_PROXY_INSPECT=1", service,
                   "/trusted/bin/jj-proxy", "-R", repo, "log", "-r", revision,
                   "--no-graph", "-T", template).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="shared-workspaces-") as directory:
        root = Path(directory).resolve()
        home = root / "home"
        (home / "src").mkdir(parents=True)
        project = home / "src/project"
        dotfiles = root / "external-dotfiles"
        (root / "jj-shim").write_bytes((DIRECTORY / "fixtures/shared-workspace-jj.sh").read_bytes())
        (root / "jj-shim").chmod(0o755)
        try:
            run("docker", "volume", "create", volume)
            volumes.append(volume)
            seed = ["docker", "run", "--rm", "--user", "0:0", "--network", "none",
                    "--mount", f"type=volume,src={volume},dst=/fixture", "--entrypoint", "/trusted/bin/busybox"]

            def copy_fixture():
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as tar:
                    for path in root.iterdir():
                        tar.add(path, arcname=path.name)
                result = subprocess.run([*seed, "--interactive", image, "tar", "xf", "-", "-C", "/fixture"],
                                        input=archive.getvalue(), cwd=ROOT, capture_output=True)
                if result.returncode:
                    raise RuntimeError(result.stderr.decode())
                run(*seed, image, "chown", "-R", "65532:65532", "/fixture")

            copy_fixture()
            initialize_fixture_metadata(run, image, volume, root, linked=linked)
            # Native Git discovery needs a local snapshot of the same metadata.
            # JJ discovery stays in the pinned image; host JJ may be older.
            exported = subprocess.run([*seed, image, "tar", "cf", "-", "-C", "/fixture", "."],
                                      cwd=ROOT, capture_output=True, check=True)
            with tarfile.open(fileobj=io.BytesIO(exported.stdout), mode="r:") as tar:
                tar.extractall(root, filter="data")
            (dotfiles / "skills/example").mkdir(parents=True)
            (dotfiles / "skills/example/SKILL.md").write_text("shared skill\n")
            (dotfiles / "unrelated").write_text("leave uncommitted\n")
            (dotfiles / ".agents/sandbox").mkdir(parents=True)
            (dotfiles / ".agents/sandbox/policy").write_text("protected\n")

            def metadata_runner(arguments, *, capture, cwd=None):
                if arguments[0] == "jj":
                    return run(*fixture_jj_container(volume, root, cwd),
                               "--entrypoint", "/trusted/bin/jj", image,
                               "--config-file", "/trusted/jj.toml", *arguments[1:])
                return subprocess.run(arguments, check=True, text=True, capture_output=capture, cwd=cwd)

            layouts = [discover_workspace(project, Path("/src/project"), home, runner=metadata_runner),
                       discover_workspace(dotfiles, Path("/src/dotfiles"), home, runner=metadata_runner)]
            for layout in layouts:
                ensure_request_lock(layout)
            staging = root / "proxy-staging"
            staging.mkdir()
            records = [layout.to_dict() for layout in layouts]
            with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                    mock.patch.object(module["OUTER_RUNTIME"], "nonrecursive_bind", Docker.nonrecursive_bind):
                mounts = module["shared_workspace_mount_args"](records, staging)
            # Capture launcher-owned guest overlays from the same fixture authority.
            guest_staging = root / "guest-staging"
            guest_staging.mkdir()
            from types import SimpleNamespace
            state = SimpleNamespace(home=home, repository=project, container_repository=Path("/src/project"),
                                    git_repository=project / ".git", git_mount_source=project / ".git",
                                    skills_tmp=guest_staging, workspaces=layouts)
            with mock.patch.object(launcher["OUTER_RUNTIME"], "nonrecursive_bind", Docker.nonrecursive_bind):
                guest_mounts = launcher["agent_repository_mounts"](state)
            copy_fixture()
            run(*seed, image, "cp", "/trusted/bin/jj", "/fixture/jj-real")
            run(*seed, image, "chown", "-R", "65532:65532", "/fixture")
            daemon_root = Path(run("docker", "volume", "inspect", "--format", "{{.Mountpoint}}", volume).stdout.strip())

            def relocate(arguments):
                result = []
                for arg in arguments:
                    fields = arg.split(",")
                    for index, field in enumerate(fields):
                        if field.startswith("src="):
                            relative = Path(field.removeprefix("src=")).relative_to(root)
                            fields[index] = "src=" + str(daemon_root / relative)
                    result.append(",".join(fields))
                return result

            authority = module["workspace_environment"](records)
            for service in services:
                run("docker", "run", "--detach", "--name", service, "--user", "65532:65532",
                    "--network", "none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
                    "--tmpfs", "/tmp:mode=1777", "--tmpfs", "/run/sandbox-proxy:mode=1777",
                    "--workdir", "/src/project", "--env", "JJ_PROXY_REPO=/src/project",
                    "--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxy",
                    "--env", "JJ_PROXY_WORKSPACES=" + authority,
                    *relocate(mounts),
                    "--mount", f"type=bind,src={daemon_root / 'jj-shim'},dst=/trusted/bin/jj,readonly",
                    "--mount", f"type=bind,src={daemon_root / 'jj-real'},dst=/trusted/bin/jj-real,readonly",
                    image)
                containers.append(service)
            for service in services:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = run("docker", "exec", "--workdir", "/src/project", service,
                                 "/trusted/bin/jj-proxy", ":ready", check=False)
                    if result.returncode == 0:
                        break
                    status = run("docker", "inspect", "--format", "{{.State.Running}}", service).stdout.strip()
                    if status != "true":
                        raise RuntimeError(run("docker", "logs", service).stderr)
                    time.sleep(0.05)
                else:
                    raise RuntimeError(f"workspace server not ready: {result.stderr}")

            finish(request(services[0], "Pi-D", "-R", "/src/sibling", "status"))
            for unlisted in (["/src/sibling", "/src/linked-source"] if linked else ["/src/sibling"]):
                denied = request(services[0], "Pi-D", "-R", unlisted, "commit", "-m", "Must be rejected")
                stdout, stderr = denied.communicate(timeout=20)
                if denied.returncode == 0:
                    raise RuntimeError(f"unlisted workspace became writable: {unlisted}: {stdout}\n{stderr}")
            before = query(services[0], "/src/project", "@", "commit_id ++ author.name()")
            a = request(services[0], "Pi-A", "-R", "/src/dotfiles", "commit", "root:skills/example", "-m", "A skill")
            wait_marker(services[0], "paused-a", a)
            b = request(services[1], "Pi-B", "-R", "/src/dotfiles", "commit", "root:unrelated", "-m", "B unrelated")
            time.sleep(0.3)
            if b.poll() is not None or marker(services[1], "entered-b"):
                raise RuntimeError("second proxy entered mutation during A's attribution sequence")
            run("docker", "exec", services[0], "/trusted/bin/busybox", "touch", "/run/sandbox-proxy/release-a")
            finish(a)
            finish(b)
            for description, identity in (("A skill", "Pi-A"), ("B unrelated", "Pi-B")):
                value = query(services[0], "/src/dotfiles", fixture_commit_revision(description),
                              'author.name() ++ "|" ++ committer.name()')
                if value != identity + "|" + identity:
                    raise RuntimeError(f"wrong cross-proxy attribution: {description}: {value}")
            if query(services[0], "/src/project", "@", "commit_id ++ author.name()") != before:
                raise RuntimeError("cross-repository commit rewrote its invoking workspace")
            files = run("docker", "exec", "--workdir", "/src/dotfiles", "--env", "JJ_PROXY_INSPECT=1", services[0],
                        "/trusted/bin/jj-proxy", "-R", "/src/dotfiles", "diff", "-r", fixture_commit_revision("A skill"),
                        "--name-only").stdout.strip()
            if files != "skills/example/SKILL.md":
                raise RuntimeError(f"scoped commit included unrelated changes: {files}")

            # A non-hook mutation must use the same lock; independent stores must not.
            for marker_name in ("paused-a", "release-a", "pause-complete"):
                run("docker", "exec", services[0], "/trusted/bin/busybox", "rm", "-f",
                    "/run/sandbox-proxy/" + marker_name)
            run("docker", "exec", services[1], "/trusted/bin/busybox", "rm", "-f", "/run/sandbox-proxy/entered-b")
            a = request(services[0], "Pi-A", "-R", "/src/dotfiles", "commit", "-m", "A empty")
            wait_marker(services[0], "paused-a", a)
            independent = request(services[1], "Pi-C", "new", "-m", "Independent project")
            finish(independent)
            b = request(services[1], "Pi-B", "-R", "/src/dotfiles", "new", "-m", "B new")
            time.sleep(0.3)
            if b.poll() is not None or marker(services[1], "entered-b"):
                raise RuntimeError("non-hook mutation bypassed the shared repository lock")
            run("docker", "exec", services[0], "/trusted/bin/busybox", "touch", "/run/sandbox-proxy/release-a")
            finish(a)
            finish(b)

            # Exercise actual guest worktree/metadata/policy modes, not only argument strings.
            guest = prefix + "-guest"
            containers.append(guest)
            shell = DIRECTORY / "fixtures/shared-workspace-guest.sh"
            result = run("docker", "run", "--rm", "--interactive", "--name", guest,
                         "--user", "65532:65532", "--network", "none", "--cap-drop=ALL",
                         "--read-only", *relocate(guest_mounts), "--workdir", "/src/project",
                         "--entrypoint", "/trusted/bin/sh", image, input=shell.read_text())
            if result.stdout != "shared-workspace-guest-ok\n":
                raise RuntimeError(f"unexpected guest workspace result: {result.stdout}\n{result.stderr}")
            layout = "linked absolute-pointer bind aliases" if linked else "ordinary metadata"
            print(f"PASS: {layout}; two roots, cross-proxy attribution/locking, scoped filesets, sibling inspection, guest protection", flush=True)
        except BaseException:
            for service in containers:
                logs = run("docker", "logs", service, check=False)
                if logs.stdout or logs.stderr:
                    print(f"{service}:\n{logs.stdout}\n{logs.stderr}", file=__import__("sys").stderr)
            raise
        finally:
            for service in containers:
                run("docker", "rm", "-f", service, check=False)
            for process in clients:
                if process.poll() is None:
                    process.kill()
                process.communicate()
            for name in reversed(volumes):
                run("docker", "volume", "rm", name, check=False)
