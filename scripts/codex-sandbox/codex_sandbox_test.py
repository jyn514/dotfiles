from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "bin" / "codex-sandbox"
AGENT_SANDBOX_DOCKERFILE = ROOT / "lib" / "agent-sandbox" / "Dockerfile"
AGENT_WRAPPERS_PROFILE = ROOT / "lib" / "agent-sandbox" / "agent-wrappers-path.sh"
DOTFILES_PROFILE = ROOT / "lib" / "agent-sandbox" / "dotfiles-profile.sh"
SANDBOX_GITCONFIG = ROOT / "lib" / "agent-sandbox" / "gitconfig"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)


def read_calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t")[1:] for line in path.read_text(encoding="utf-8").splitlines()]


class AgentSandboxImageTest(unittest.TestCase):
    def test_login_profile_restores_agent_wrappers_path(self) -> None:
        result = subprocess.run(
            ["sh", "-c", f'. "{AGENT_WRAPPERS_PROFILE}"; printf "%s\\n" "$PATH"'],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "/lib/agent-wrappers:/usr/local/bin:/usr/bin:/bin\n",
            result.stdout,
        )
        self.assertIn(
            "COPY ./lib/agent-sandbox/agent-wrappers-path.sh /etc/profile.d/agent-wrappers-path.sh",
            AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8"),
        )

    def test_dotfiles_profile_is_noninteractive_and_image_managed(self) -> None:
        result = subprocess.run(
            [
                "sh",
                "-c",
                f'. "{DOTFILES_PROFILE}"; '
                'printf "%s\\n" "$DOTFILES_SANDBOX|$MAKEFLAGS|$PAGER|$EDITOR|$CARGO_HOME"',
            ],
            env={"HOME": "/sandbox-home", "PATH": "/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "1|-j4|cat|vi|/sandbox-home/.local/lib/cargo\n", result.stdout
        )

        path_result = subprocess.run(
            ["sh", "-c", f'. "{DOTFILES_PROFILE}"; printf "%s\\n" "$PATH"'],
            env={"HOME": "/sandbox-home", "PATH": "/usr/local/bin:/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "/lib/agent-wrappers:/opt/agent-tools/bin:/opt/agent-codex/bin:"
            "/usr/local/bin:/usr/bin:/bin\n",
            path_result.stdout,
        )
        profile = DOTFILES_PROFILE.read_text(encoding="utf-8")
        for interactive_hook in ("mise activate", "prompt-command", "keychain", "direnv"):
            self.assertNotIn(interactive_hook, profile)

        dockerfile = AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8")
        for source in (
            "./lib/agent-sandbox/dotfiles-profile.sh",
            "./lib/agent-sandbox/gitconfig",
            "./config/editorconfig",
            "./config/inputrc",
        ):
            self.assertIn(source, dockerfile)

    def test_sandbox_gitconfig_keeps_diff_semantics_without_identity_or_credentials(self) -> None:
        result = subprocess.run(
            ["git", "config", "--file", str(SANDBOX_GITCONFIG), "--get", "diff.algorithm"],
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual("histogram\n", result.stdout)
        config = SANDBOX_GITCONFIG.read_text(encoding="utf-8")
        self.assertNotIn("[user]", config)
        self.assertNotIn("[credential]", config)


class CodexSandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo with spaces"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".jj" / "repo").mkdir(parents=True)
        self.home = self.root / "home with spaces"
        (self.home / ".agents" / "skills").mkdir(parents=True)
        (self.home / ".codex" / "rules").mkdir(parents=True)
        (self.home / "src").mkdir()
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.docker_log = self.root / "docker.log"
        self.python_log = self.root / "python.log"

        write_executable(self.fake_bin / "jj", """
            #!/bin/sh
            [ "$1" = workspace ] && [ "$2" = root ] || exit 2
            printf '%s\n' "$FAKE_REPOSITORY"
        """)
        write_executable(self.fake_bin / "git", """
            #!/bin/sh
            case " $* " in
                *" rev-parse "*)
                    printf '%s\n%s\n' "${FAKE_GIT_DIR:-$FAKE_REPOSITORY/.git}" \
                        "${FAKE_GIT_COMMON_DIR:-$FAKE_REPOSITORY/.git}"
                    ;;
                *) exec /usr/bin/git "$@" ;;
            esac
        """)
        write_executable(self.fake_bin / "uname", """
            #!/bin/sh
            printf '%s\n' "${FAKE_UNAME:-Linux}"
        """)
        write_executable(self.fake_bin / "docker", """
            #!/bin/sh
            {
                printf 'CALL'
                for argument do printf '\t%s' "$argument"; done
                printf '\n'
            } >> "$FAKE_DOCKER_LOG"
            if [ "$1 $2" = "network exists" ]; then
                [ "${FAKE_NETWORK_EXISTS:-1}" = 1 ]
                exit
            fi
            if [ "$1 $2" = "network create" ] && [ "${FAKE_NETWORK_CREATE_FAIL:-0}" = 1 ]; then
                exit 44
            fi
            if [ "$1 $2" = "image inspect" ]; then
                [ "${FAKE_IMAGE_EXISTS:-1}" = 1 ]
                exit
            fi
            if [ "$1" = build ]; then
                previous=
                for argument do
                    if [ "$previous" = --iidfile ]; then
                        printf '%s\n' 'sha256:built-image-id' > "$argument"
                        break
                    fi
                    previous=$argument
                done
                exit 0
            fi
            if [ "$1" = inspect ]; then
                printf '%s\n' "${FAKE_RELAY_IP:-}"
                exit 0
            fi
            if [ "$1" = run ]; then
                if [ "${FAKE_AGENT_BLOCK:-0}" = 1 ]; then
                    : > "$FAKE_AGENT_READY"
                    trap 'exit 143' HUP INT TERM
                    while :; do sleep 1; done
                fi
                exit "${FAKE_AGENT_EXIT:-0}"
            fi
            exit 0
        """)
        write_executable(self.fake_bin / "python3", """
            #!/bin/sh
            {
                printf 'CALL'
                for argument do printf '\t%s' "$argument"; done
                printf '\n'
            } >> "$FAKE_PYTHON_LOG"
            action=$2
            shift 2
            value_for() {
                wanted=$1
                shift
                while [ "$#" -gt 0 ]; do
                    if [ "$1" = "$wanted" ]; then printf '%s\n' "$2"; return; fi
                    shift
                done
                return 1
            }
            case "$action" in
                snapshot)
                    output=$(value_for --output "$@")
                    printf '%s\n' '{"version":1,"commands":{"jj":{}}}' > "$output"
                    ;;
                hold-lock)
                    ready=$(value_for --ready "$@")
                    coordinated=$(value_for --coordinated "$@")
                    release=$(value_for --release "$@")
                    : > "$ready"
                    while [ ! -e "$coordinated" ]; do sleep 0.01; done
                    while [ ! -e "$release" ]; do sleep 0.01; done
                    ;;
                attach)
                    state=$(value_for --state "$@")
                    printf '%s\n' '{"proxies":[]}' > "$state"
                    ;;
                agent-args)
                    output=$(value_for --output "$@")
                    printf '%s\n' '--env' 'SANDBOX_PROXY_DIR=/run/sandbox-proxies' > "$output"
                    ;;
                monitor) ;;
                *) exit 91 ;;
            esac
        """)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def launcher_environment(self, **updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update({
            "PATH": f"{self.fake_bin}:{environment['PATH']}",
            "HOME": str(self.home),
            "FAKE_REPOSITORY": str(self.repo),
            "FAKE_DOCKER_LOG": str(self.docker_log),
            "FAKE_PYTHON_LOG": str(self.python_log),
            "AGENT_PODMAN_ACCESS_DIR": str(self.root / "no-agent-podman"),
            "FAKE_NETWORK_EXISTS": "1",
            "FAKE_UNAME": "Linux",
        })
        environment.update(updates)
        return environment

    def run_launcher(self, *arguments: str, **updates: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *arguments], cwd=self.repo,
            env=self.launcher_environment(**updates),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )

    def final_run(self) -> list[str]:
        runs = [call for call in read_calls(self.docker_log) if call[:1] == ["run"] and "-it" in call]
        self.assertEqual(1, len(runs))
        return runs[0]

    def test_constructs_secured_agent_and_trusted_proxy_arguments(self) -> None:
        result = self.run_launcher("resume", "session-id")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertIn("--cap-drop=ALL", run)
        self.assertIn("--security-opt=no-new-privileges", run)
        self.assertIn(f"type=bind,src={self.repo.resolve()},dst=/src/work,bind-nonrecursive=true", run)
        self.assertIn(f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/work/.git,readonly", run)
        self.assertIn(f"type=bind,src={(self.repo / '.jj').resolve()},dst=/src/work/.jj,readonly", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertLess(run.index("resume"), run.index("session-id"))

        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        self.assertEqual(1, len(snapshots))
        builder = snapshots[0][snapshots[0].index("--jj-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "jj-proxy-image", Path(builder).resolve())

    def test_accepts_linked_git_worktree_metadata(self) -> None:
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: ../main/.git/worktrees/repo\n", encoding="utf-8")
        git_dir = self.root / "main" / ".git" / "worktrees" / "repo"
        common_dir = self.root / "main" / ".git"
        git_dir.mkdir(parents=True)
        result = self.run_launcher(
            FAKE_GIT_DIR=str(git_dir), FAKE_GIT_COMMON_DIR=str(common_dir),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        repository = self.repo.resolve()
        self.assertIn(
            f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/work/.git,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={repository},dst={repository},readonly,bind-nonrecursive=true",
            run,
        )
        self.assertIn(
            f"type=bind,src={common_dir.resolve()},dst={common_dir.resolve()},readonly",
            run,
        )
        relative_target = Path(os.path.normpath(
            Path("/src/work") / os.path.relpath(common_dir.resolve(), self.repo.resolve())
        ))
        self.assertIn(
            f"type=bind,src={common_dir.resolve()},dst={relative_target},readonly",
            run,
        )
        relative_repository = Path(os.path.normpath(
            relative_target / os.path.relpath(repository, common_dir.resolve())
        ))
        self.assertIn(
            f"type=bind,src={repository},dst={relative_repository},readonly,bind-nonrecursive=true",
            run,
        )
        self.assertNotIn(
            f"type=bind,src={git_dir.resolve()},dst={git_dir.resolve()},readonly",
            run,
        )

    def test_does_not_scan_trusted_host_metadata_for_hard_links(self) -> None:
        metadata = self.repo / ".jj" / "trusted-metadata"
        metadata.write_text("trusted", encoding="utf-8")
        os.link(metadata, self.repo / ".jj" / "trusted-metadata-link")
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_preserves_agent_exit_status_and_cleans_up(self) -> None:
        result = self.run_launcher(FAKE_AGENT_EXIT="23")
        self.assertEqual(23, result.returncode, result.stderr)
        removals = [call for call in read_calls(self.docker_log) if call[:2] == ["rm", "--force"]]
        self.assertEqual(1, len(removals))
        self.assertRegex(removals[0][2], r"^codex-sandbox-[0-9]+-[0-9]+$")
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertIn("hold-lock", actions)

    def test_creates_network_with_public_only_routes(self) -> None:
        result = self.run_launcher(FAKE_NETWORK_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        creates = [call for call in read_calls(self.docker_log) if call[:2] == ["network", "create"]]
        self.assertEqual(1, len(creates))
        self.assertIn("--route", creates[0])
        self.assertIn("10.0.0.0/8,prohibit", creates[0])
        self.assertIn("192.168.0.0/16,prohibit", creates[0])
        self.assertEqual("codex-public-only", creates[0][-1])

    def test_fresh_build_runs_agent_by_immutable_image_id(self) -> None:
        result = self.run_launcher(FAKE_IMAGE_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        builds = [call for call in read_calls(self.docker_log) if call[:1] == ["build"]]
        self.assertEqual(1, len(builds))
        self.assertIn("sha256:built-image-id", self.final_run())

    def test_network_failure_stops_before_lock_and_proxy_start(self) -> None:
        result = self.run_launcher(FAKE_NETWORK_EXISTS="0", FAKE_NETWORK_CREATE_FAIL="1")
        self.assertEqual(1, result.returncode)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertEqual(["snapshot"], actions)
        self.assertFalse(any(call[:1] == ["run"] for call in read_calls(self.docker_log)))

    def test_staging_ignores_dangling_skill_links(self) -> None:
        skills = self.home / ".agents" / "skills"
        (skills / "missing").symlink_to(self.root / "missing-skill", target_is_directory=True)
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.final_run()

    def test_term_signal_cleans_running_agent_and_proxies(self) -> None:
        ready = self.root / "agent-ready"
        process = subprocess.Popen(
            [sys.executable, str(LAUNCHER)], cwd=self.repo,
            env=self.launcher_environment(FAKE_AGENT_BLOCK="1", FAKE_AGENT_READY=str(ready)),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.01)
        if not ready.exists():
            os.killpg(process.pid, signal.SIGTERM)
            self.fail(f"agent did not start: {process.communicate(timeout=5)!r}")
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(143, process.returncode, (stdout, stderr))
        removals = [call for call in read_calls(self.docker_log) if call[:2] == ["rm", "--force"]]
        self.assertEqual(1, len(removals))
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertIn("hold-lock", actions)

    def test_non_linux_omits_native_linux_restrictions(self) -> None:
        result = self.run_launcher(FAKE_UNAME="Darwin")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertNotIn("--cap-drop=ALL", run)
        self.assertNotIn("--security-opt=no-new-privileges", run)
        self.assertNotIn("native Linux sandboxing", result.stderr)

    def test_agent_podman_relay_is_isolated_and_injected(self) -> None:
        access = self.root / "agent-podman"
        access.mkdir()
        (access / "connection.env").write_text(
            "AGENT_PODMAN_SSH_USER=worker\n"
            "AGENT_PODMAN_SSH_PORT=2223\n"
            "CONTAINER_HOST=ssh://worker@host.docker.internal:2223/run/user/501/podman.sock\n"
            "CONTAINER_SSHKEY=/run/secrets/agent-podman-key\n",
            encoding="utf-8",
        )
        (access / "id_ed25519").write_text("key", encoding="utf-8")
        (access / "known_hosts.sandbox").write_text("host", encoding="utf-8")
        result = self.run_launcher(
            AGENT_PODMAN_ACCESS_DIR=str(access), FAKE_RELAY_IP="10.0.0.8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay_runs = [call for call in calls if call[:2] == ["run", "--detach"]]
        self.assertEqual(1, len(relay_runs))
        self.assertIn("--cap-drop=ALL", relay_runs[0])
        self.assertIn("--read-only", relay_runs[0])
        run = self.final_run()
        self.assertIn("CONTAINER_HOST=ssh://worker@10.0.0.8:2222/run/user/501/podman.sock", run)
        self.assertIn(
            f"type=bind,src={access / 'id_ed25519'},dst=/run/secrets/agent-podman-key,readonly",
            run,
        )

    def test_rejects_incomplete_agent_podman_configuration(self) -> None:
        access = self.root / "agent-podman"
        access.mkdir()
        (access / "connection.env").write_text("CONTAINER_HOST=x\n", encoding="utf-8")
        result = self.run_launcher(AGENT_PODMAN_ACCESS_DIR=str(access))
        self.assertEqual(1, result.returncode)
        self.assertIn("Agent Podman access state is incomplete", result.stderr)
        self.assertEqual([], read_calls(self.docker_log))


if __name__ == "__main__":
    unittest.main()
