from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "codex-sandbox"
LAUNCHER = TOOL / "codex-sandbox"
AGENT_SANDBOX_DOCKERFILE = TOOL / "image" / "Dockerfile"
AGENT_SANDBOX_INSTALL_DEPS = TOOL / "image" / "install-deps.sh"
AGENT_WRAPPERS_PROFILE = TOOL / "image" / "agent-wrappers-path.sh"
DOTFILES_PROFILE = TOOL / "image" / "dotfiles-profile.sh"
SANDBOX_GITCONFIG = TOOL / "image" / "gitconfig"
PI_LAUNCHER = TOOL / "image" / "pi"
PI_REVISION = "a4a3cfc16b9dec18868c69979c75d88fa922702c"


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
            "/libexec/agent-wrappers:/usr/local/bin:/usr/bin:/bin\n",
            result.stdout,
        )
        self.assertIn(
            "COPY ./tools/codex-sandbox/image/agent-wrappers-path.sh /etc/profile.d/agent-wrappers-path.sh",
            AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8"),
        )

    def test_bb_wrapper_runtime_is_copied_into_image(self) -> None:
        dockerfile = AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("./tools/agent-split /tools/agent-split", dockerfile)
        self.assertIn("/usr/local/bin/bb", dockerfile)
        self.assertRegex(
            AGENT_SANDBOX_INSTALL_DEPS.read_text(encoding="utf-8"),
            r"(?m)^        gcompat \\$",
        )
        self.assertIn("./lib/shell/lib.sh /lib/shell/lib.sh", dockerfile)
        self.assertNotIn("tools/codex-auth-proxy/server.py", dockerfile)
        self.assertIn(
            "tools/codex-auth-proxy/server.py /trusted/bin/codex-auth-proxy",
            (ROOT / "tools/codex-auth-proxy/Dockerfile").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "../../tools/agent-split/bb",
            os.readlink(ROOT / "libexec" / "agent-wrappers" / "bb"),
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
            "/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:"
            "/usr/local/bin:/usr/bin:/bin\n",
            path_result.stdout,
        )
        profile = DOTFILES_PROFILE.read_text(encoding="utf-8")
        for interactive_hook in ("mise activate", "prompt-command", "keychain", "direnv"):
            self.assertNotIn(interactive_hook, profile)

        dockerfile = AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8")
        for source in (
            "./tools/codex-sandbox/image/dotfiles-profile.sh",
            "./tools/codex-sandbox/image/gitconfig",
            "./config/editorconfig",
            "./config/inputrc",
        ):
            self.assertIn(source, dockerfile)
        self.assertIn("https://github.com/jyn514/pi.git", dockerfile)
        self.assertIn(f"ARG PI_REVISION={PI_REVISION}", dockerfile)
        self.assertIn("FROM node:24-alpine3.22 AS pi-build", dockerfile)
        self.assertIn("npm ci --ignore-scripts --prefix /opt/pi-npm", dockerfile)
        self.assertIn("./tools/pi-npm/package-lock.json", dockerfile)
        self.assertIn("npm ci --ignore-scripts --prefix /opt/agent-pi/src", dockerfile)
        self.assertIn("npm run hydrate:model-data --prefix /opt/agent-pi/src", dockerfile)
        self.assertIn("npm run build:offline --prefix /opt/agent-pi/src", dockerfile)
        self.assertIn('ENTRYPOINT ["pi", "--offline", "--approve"]', dockerfile)

    def test_pi_runtime_builds_the_pinned_fork_for_any_libc(self) -> None:
        dockerfile = AGENT_SANDBOX_DOCKERFILE.read_text(encoding="utf-8")
        launcher = PI_LAUNCHER.read_text(encoding="utf-8")

        self.assertIn(f"ARG PI_REVISION={PI_REVISION}", dockerfile)
        self.assertIn('test "$(git -C /opt/agent-pi/src rev-parse HEAD)" = "${PI_REVISION}"', dockerfile)
        self.assertIn("COPY --link --from=pi-build /opt/agent-pi", dockerfile)
        self.assertNotIn("earendil-works/pi/releases", dockerfile)
        self.assertIn("major === 22 && minor >= 19", launcher)
        self.assertIn("/opt/agent-pi/src/packages/coding-agent/dist/cli.js", launcher)

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
        self.codex_log = self.root / "codex.log"

        write_executable(self.fake_bin / "codex", """
            #!/bin/sh
            printf '%s\t%s\n' "$CODEX_HOME" "$*" > "$FAKE_CODEX_LOG"
        """)
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
                case " $* " in
                    *" --format "*) printf 'sha256:%064d\n' 0; exit 0 ;;
                esac
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
                case " $* " in
                    *" {{.State.Running}} "*) printf '%s\n' true ;;
                    *) printf '%s\n' "${FAKE_RELAY_IP:-}" ;;
                esac
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
                    printf '%s\n' "${FAKE_SESSION:-new}" > "$ready"
                    while [ ! -e "$coordinated" ]; do sleep 0.01; done
                    while [ ! -e "$release" ]; do sleep 0.01; done
                    ;;
                attach)
                    state=$(value_for --state "$@")
                    if [ -n "$FAKE_PROXY_STATE" ]; then
                        printf '%s\n' "$FAKE_PROXY_STATE" > "$state"
                    else
                        printf '%s\n' '{"proxies":[]}' > "$state"
                    fi
                    ;;
                agent-args|finalize)
                    output=$(value_for --output "$@")
                    printf '%s\n' '--env' 'SANDBOX_PROXY_DIR=/run/sandbox-proxies' > "$output"
                    ;;
                publish|monitor) ;;
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
            "FAKE_CODEX_LOG": str(self.codex_log),
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

    def test_stages_repository_skill_links_as_container_workspace_links(self) -> None:
        repository_skill = self.repo / ".agents" / "skills" / "tighten-docs"
        repository_skill.mkdir(parents=True)
        (repository_skill / "SKILL.md").write_text("repository skill\n", encoding="utf-8")
        external_skill = self.root / "external-skill"
        external_skill.mkdir()
        (external_skill / "SKILL.md").write_text("external skill\n", encoding="utf-8")
        skills = self.home / ".agents" / "skills"
        (skills / "tighten-docs").symlink_to(repository_skill, target_is_directory=True)
        (skills / "external").symlink_to(external_skill, target_is_directory=True)

        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            staged = state.skills_tmp / "skills"
            self.assertEqual(
                "/src/work/.agents/skills/tighten-docs",
                os.readlink(staged / "tighten-docs"),
            )
            self.assertFalse((staged / "external").is_symlink())
            self.assertEqual(
                "external skill\n",
                (staged / "external" / "SKILL.md").read_text(encoding="utf-8"),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

    def test_browser_oauth_login_uses_dedicated_codex_home(self) -> None:
        result = self.run_launcher("auth", "login")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.home / '.codex-sandbox-auth'}\tlogin\n",
            self.codex_log.read_text(encoding="utf-8"),
        )
        self.assertEqual(0o700, (self.home / ".codex-sandbox-auth").stat().st_mode & 0o777)
        self.assertEqual([], read_calls(self.docker_log))

    def test_constructs_secured_agent_and_trusted_proxy_arguments(self) -> None:
        result = self.run_launcher("resume", "session-id")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertIn("--cap-drop=ALL", run)
        self.assertIn("--security-opt=no-new-privileges", run)
        self.assertIn(f"type=bind,src={self.repo.resolve()},dst=/src/work,bind-nonrecursive=true", run)
        self.assertIn(f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/work/.git,readonly", run)
        self.assertIn(f"type=bind,src={(self.repo / '.jj').resolve()},dst=/src/work/.jj,readonly", run)
        pi_agent = self.home / ".pi/agent"
        self.assertIn(
            f"type=bind,src={pi_agent},dst=/home/codex/.pi/agent",
            run,
        )
        auth_mounts = [
            item for item in run
            if item.endswith("dst=/home/codex/.pi/agent/auth.json,readonly")
        ]
        self.assertEqual(1, len(auth_mounts))
        auth_mask = Path(auth_mounts[0].split(",src=", 1)[1].split(",dst=", 1)[0])
        self.assertFalse(auth_mask.exists())
        staged_mounts = [
            item for item in run
            if any(item.endswith(f"dst={destination},readonly") for destination in (
                "/home/codex/.agents/shared.md",
                "/home/codex/.pi/agent/AGENTS.md",
                "/home/codex/.pi/agent/settings.json",
                "/home/codex/.pi/agent/mcp.json",
            ))
        ]
        self.assertEqual(4, len(staged_mounts))
        staged_sources = [
            Path(item.split(",src=", 1)[1].split(",dst=", 1)[0])
            for item in staged_mounts
        ]
        self.assertEqual(1, len({source.parent for source in staged_sources}))
        self.assertTrue(all(not source.is_relative_to(ROOT) for source in staged_sources))
        self.assertNotIn("pi-agent-", " ".join(run))
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertLess(run.index("resume"), run.index("session-id"))

        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        self.assertEqual(1, len(snapshots))
        builder = snapshots[0][snapshots[0].index("--jj-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "jj-proxy-image", Path(builder).resolve())

    def test_enables_trusted_zulip_proxy_when_credentials_exist(self) -> None:
        zuliprc = self.home / ".zuliprc"
        zuliprc.write_text("[api]\nkey=secret\n", encoding="utf-8")
        zuliprc.chmod(0o600)
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        snapshot = snapshots[0]
        builder = snapshot[snapshot.index("--zulip-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "zulip-proxy-image", Path(builder).resolve())
        self.assertEqual(str(zuliprc), snapshot[snapshot.index("--zuliprc") + 1])
        attaches = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "attach"]
        self.assertEqual(str(zuliprc), attaches[0][attaches[0].index("--zuliprc") + 1])

    def test_starts_codex_auth_sidecar_without_mounting_auth_in_agent(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        sidecars = [
            call for call in calls
            if call[:2] == ["run", "--detach"] and any("codex-auth-proxy-" in item for item in call)
        ]
        self.assertEqual(1, len(sidecars))
        sidecar = sidecars[0]
        self.assertIn(
            f"type=bind,src={auth.resolve()},dst=/var/lib/codex-auth", sidecar,
        )
        self.assertIn("--read-only", sidecar)
        self.assertEqual("sha256:" + "0" * 64, sidecar[-1])
        sidecar_name = sidecar[sidecar.index("--name") + 1]
        readiness = [call for call in calls if call[:3] == [
            "exec", sidecar_name, "/usr/local/bin/python3",
        ]]
        self.assertEqual(1, len(readiness))
        agent = self.final_run()
        self.assertFalse(any(str(auth) in item for item in agent))
        self.assertTrue(any(item.startswith("CODEX_SIDECAR_URL=http://codex-auth-proxy-") for item in agent))
        self.assertIn(
            f"type=bind,src={ROOT / 'tools/codex-auth-proxy/pi-extension'},"
            "dst=/home/codex/.pi/agent/extensions/codex-sidecar,readonly",
            agent,
        )

    def test_reuses_auth_sidecar_from_persistent_proxy_session(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher(
            FAKE_SESSION="shared",
            FAKE_PROXY_STATE=(
                '{"proxies":[],"auth":{"container":"shared-auth-proxy",'
                '"key":"shared-key"}}'
            ),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        self.assertFalse(any(
            call[:2] == ["run", "--detach"] and "shared-auth-proxy" in call
            for call in calls
        ))
        agent = self.final_run()
        self.assertIn("CODEX_SIDECAR_URL=http://shared-auth-proxy:8787", agent)
        self.assertIn("CODEX_SIDECAR_KEY=shared-key", agent)

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
        self.assertEqual(2, len(builds))
        self.assertTrue(any("tools/codex-auth-proxy/Dockerfile" in call for call in builds))
        self.assertTrue(any("tools/codex-sandbox/image/Dockerfile" in call for call in builds))
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
        self.assertEqual(
            "sha256:" + "0" * 64,
            relay_runs[0][relay_runs[0].index("/usr/bin/socat") + 1],
        )
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
