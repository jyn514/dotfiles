from __future__ import annotations

import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "codex-sandbox"
LAUNCHER = TOOL / "codex-sandbox"
AGENT_WRAPPERS_PROFILE = TOOL / "image" / "agent-wrappers-path.sh"
DOTFILES_PROFILE = TOOL / "image" / "dotfiles-profile.sh"
SANDBOX_GITCONFIG = TOOL / "image" / "gitconfig"
SANDBOX_DOCKERFILE = TOOL / "image" / "Dockerfile"
HOST_EDITOR_CLIENT = TOOL / "image" / "host-editor"
HOST_EDITOR_PANE = TOOL / "host-editor-pane"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)


def read_calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t")[1:] for line in path.read_text(encoding="utf-8").splitlines()]


class AgentSandboxImageTest(unittest.TestCase):
    def test_pi_build_uses_lockfile_pinned_model_data(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("npm run hydrate:pinned-model-data", dockerfile)
        self.assertNotIn("npm run hydrate:model-data", dockerfile)

    def test_image_installs_host_editor_client(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chmod=755 ./tools/codex-sandbox/image/host-editor "
            "/opt/agent-tools/bin/host-editor",
            dockerfile,
        )
        self.assertIn("ENV EDITOR=vi VISUAL=vi", dockerfile)

    def test_woodpecker_adapter_remains_visible_after_bb_resolves_its_wrapper(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chown=${AGENT_UID}:${AGENT_GID} "
            "./tools/agent-podman/woodpecker-cli "
            "/opt/agent-tools/bin/woodpecker-cli",
            dockerfile,
        )

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
    def test_dotfiles_profile_sets_a_noninteractive_environment(self) -> None:
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


class HostEditorPaneTest(unittest.TestCase):
    def test_runs_editor_argv_and_records_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            editor = root / "editor"
            write_executable(editor, """
                #!/bin/sh
                printf '%s\\n' "$2" > "$1"
                exit 7
            """)
            output = root / "output"
            status = root / "status"

            result = subprocess.run([
                str(HOST_EDITOR_PANE), str(status), "--",
                str(editor), str(output), "value with spaces",
            ])

            self.assertEqual(7, result.returncode)
            self.assertEqual("7\n", status.read_text(encoding="utf-8"))
            self.assertEqual("value with spaces\n", output.read_text(encoding="utf-8"))


class HostEditorBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = runpy.run_path(str(LAUNCHER))
        self.bridge = self.launcher["HostEditorBridge"]()

    def tearDown(self) -> None:
        self.bridge.stop()

    def start_bridge(self) -> None:
        self.bridge.start()
        self.bridge.allow_peers({"127.0.0.1"})

    def run_client(
        self, content: str, *, token: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "prompt.md"
            document.write_text(content, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HOST_EDITOR_CLIENT), str(document)],
                env={
                    **os.environ,
                    "CODEX_SANDBOX_EDITOR_ADDRESS": f"127.0.0.1:{self.bridge.port}",
                    "CODEX_SANDBOX_EDITOR_TOKEN": token or self.bridge.token,
                },
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            )
            return result, document.read_text(encoding="utf-8")

    def test_guest_client_round_trips_only_document_text(self) -> None:
        self.bridge._edit = lambda content: content + " edited"
        self.start_bridge()

        result, content = self.run_client("draft")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("draft edited", content)

    def test_guest_client_preserves_document_when_host_editor_fails(self) -> None:
        def fail(_content: str) -> str:
            raise self.launcher["LauncherError"]("editor refused")

        self.bridge._edit = fail
        self.start_bridge()

        result, content = self.run_client("draft")

        self.assertEqual(1, result.returncode)
        self.assertIn("editor refused", result.stderr)
        self.assertEqual("draft", content)

    def test_client_rejects_linked_files_before_contacting_host(self) -> None:
        self.start_bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("draft", encoding="utf-8")
            link = root / "link"
            link.symlink_to(target)
            result = subprocess.run(
                [sys.executable, str(HOST_EDITOR_CLIENT), str(link)],
                env={
                    **os.environ,
                    "CODEX_SANDBOX_EDITOR_ADDRESS": f"127.0.0.1:{self.bridge.port}",
                    "CODEX_SANDBOX_EDITOR_TOKEN": self.bridge.token,
                },
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("unlinked regular file", result.stderr)

    def test_unapproved_network_peer_is_closed_immediately(self) -> None:
        self.bridge.start()
        connection = socket.create_connection(("127.0.0.1", self.bridge.port), timeout=1)
        connection.sendall(b"\x00\x00")

        try:
            self.assertEqual(b"", connection.recv(1))
        except ConnectionResetError:
            pass
        connection.close()

    def test_wrong_session_token_cannot_open_host_editor(self) -> None:
        self.bridge._edit = mock.Mock(return_value="changed")
        self.start_bridge()

        result, content = self.run_client("draft", token="wrong")

        self.assertEqual(1, result.returncode)
        self.assertIn("invalid host editor request", result.stderr)
        self.assertEqual("draft", content)
        self.bridge._edit.assert_not_called()

    def test_partial_request_does_not_wedge_later_edits(self) -> None:
        self.bridge._edit = lambda content: content + " edited"
        self.bridge._serve.__globals__["EDITOR_REQUEST_TIMEOUT_SECONDS"] = 0.1
        self.start_bridge()
        stalled = socket.create_connection(("127.0.0.1", self.bridge.port), timeout=1)
        stalled.sendall(b"\x00\x00")
        time.sleep(0.2)

        result, content = self.run_client("draft")

        stalled.close()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("draft edited", content)

    def test_stop_closes_listener(self) -> None:
        self.start_bridge()
        port = self.bridge.port
        self.bridge.stop()

        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.1)


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
        self.jj_log = self.root / "jj.log"

        write_executable(self.fake_bin / "codex", """
            #!/bin/sh
            printf '%s\t%s\n' "$CODEX_HOME" "$*" > "$FAKE_CODEX_LOG"
        """)
        write_executable(self.fake_bin / "jj", """
            #!/bin/sh
            {
                printf 'CALL'
                for argument do printf '\t%s' "$argument"; done
                printf '\n'
            } >> "$FAKE_JJ_LOG"
            if [ "$1 $2" = "git init" ]; then
                mkdir -p "$FAKE_REPOSITORY/.git" "$FAKE_REPOSITORY/.jj/repo"
                exit
            fi
            [ "$1 $2" = "workspace root" ] || exit 2
            [ -d "$FAKE_REPOSITORY/.jj" ] || exit 1
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
            tab=$(printf '\t')
            record=CALL
            for argument do record="${record}${tab}${argument}"; done
            printf '%s\n' "$record" >> "$FAKE_DOCKER_LOG"
            if [ "$1 $2" = "network exists" ]; then
                [ "${FAKE_NETWORK_EXISTS:-1}" = 1 ]
                exit
            fi
            if [ "$1 $2" = "network create" ] && [ "${FAKE_NETWORK_CREATE_FAIL:-0}" = 1 ]; then
                exit 44
            fi
            if [ "$1 $2" = "network inspect" ]; then
                printf '%s\n' 127.0.0.1
                exit
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
                    *"if index"*"NetworkSettings.Networks"*)
                        [ "${FAKE_SIDECAR_NETWORK:-1}" = 1 ] && printf '%s\n' true
                        ;;
                    *) printf '%s\n' "${FAKE_RELAY_IP:-10.0.0.9}" ;;
                esac
                exit 0
            fi
            if [ "$1" = run ]; then
                case " $* " in
                    *" -it "*)
                        if [ -n "$FAKE_MODEL_STORE_CAPTURE" ]; then
                            for argument do
                                case "$argument" in
                                    type=bind,src=*,dst=/home/codex/.pi/agent)
                                        agent_dir=${argument#type=bind,src=}
                                        agent_dir=${agent_dir%,dst=*}
                                        cp "$agent_dir/models-store.json" "$FAKE_MODEL_STORE_CAPTURE" || exit 42
                                        printf '{}\\n' > "$agent_dir/models-store.json"
                                        ;;
                                esac
                            done
                        fi
                        if [ "${FAKE_AGENT_BLOCK:-0}" = 1 ]; then
                            : > "$FAKE_AGENT_READY"
                            trap 'exit 143' HUP INT TERM
                            while :; do sleep 1; done
                        fi
                        exit "${FAKE_AGENT_EXIT:-0}"
                        ;;
                esac
                exit 0
            fi
            if [ "$1" = rm ] && [ -n "$FAKE_CLEANUP_DELAY" ]; then
                sleep "$FAKE_CLEANUP_DELAY"
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
        environment.pop("TMUX", None)
        environment.update({
            "PATH": f"{self.fake_bin}:{environment['PATH']}",
            "HOME": str(self.home),
            "FAKE_REPOSITORY": str(self.repo),
            "FAKE_DOCKER_LOG": str(self.docker_log),
            "FAKE_PYTHON_LOG": str(self.python_log),
            "FAKE_CODEX_LOG": str(self.codex_log),
            "FAKE_JJ_LOG": str(self.jj_log),
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

    def test_loads_repository_and_home_sandbox_instructions(self) -> None:
        repository_sandbox = self.repo / ".agents" / "sandbox"
        repository_sandbox.mkdir(parents=True)
        (repository_sandbox / "AGENTS.md").write_text(
            "@repository-rule.md\n", encoding="utf-8",
        )
        (repository_sandbox / "repository-rule.md").write_text(
            "repository rule\n", encoding="utf-8",
        )
        home_sandbox = self.home / ".agents" / "sandbox"
        home_sandbox.mkdir()
        (home_sandbox / "AGENTS.md").write_text(
            "@home-rule.md\n", encoding="utf-8",
        )
        (home_sandbox / "home-rule.md").write_text(
            "home rule\n", encoding="utf-8",
        )

        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            agents = (state.skills_tmp / "config/pi-AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(
                "@breq.md\n"
                "@coordination-dialect.md\n"
                "@/src/work/.agents/sandbox/AGENTS.md\n"
                "@../../.agents/sandbox/AGENTS.md\n",
                agents,
            )
            self.assertEqual(
                "home rule\n",
                (state.skills_tmp / "sandbox/home-rule.md").read_text(encoding="utf-8"),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(
            item.endswith("dst=/home/codex/.agents/sandbox,readonly")
            for item in self.final_run()
        ))

    def test_staged_settings_scope_external_editor_to_the_sandbox(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            settings = json.loads(
                (state.skills_tmp / "config/pi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "/opt/agent-tools/bin/host-editor", settings["externalEditor"]
            )
            source = json.loads((ROOT / "config/pi.json").read_text(encoding="utf-8"))
            self.assertNotIn("externalEditor", source)
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

    def test_mounts_subagent_configuration_from_staged_dotfiles(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            staged = state.skills_tmp / "config/pi-codex-subagents.json"
            self.assertEqual(
                json.loads((ROOT / "config/pi-codex-subagents.json").read_text(encoding="utf-8")),
                json.loads(staged.read_text(encoding="utf-8")),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(
            item.endswith(
                "/config/pi-codex-subagents.json,dst=/home/codex/.pi/agent/"
                "pi-codex-subagents/config.json,readonly"
            )
            for item in self.final_run()
        ))

    def test_launch_initializes_a_missing_jj_repository(self) -> None:
        shutil.rmtree(self.repo / ".jj")
        shutil.rmtree(self.repo / ".git")

        result = self.run_launcher()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [["workspace", "root"], ["git", "init"], ["workspace", "root"]],
            read_calls(self.jj_log),
        )
        self.assertTrue((self.repo / ".jj" / "repo").is_dir())
        self.assertTrue((self.repo / ".git").is_dir())

    def test_bare_launch_gets_a_resumable_session_id(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        arguments, session_id = launcher["resumable_arguments"]([])
        self.assertEqual(["--session-id", session_id], arguments)
        self.assertRegex(session_id, r"^[0-9a-f-]{36}$")
        self.assertEqual(
            (["--session", "existing"], "existing"),
            launcher["resumable_arguments"](["--session", "existing"]),
        )
        self.assertEqual(
            (["--resume"], None),
            launcher["resumable_arguments"](["--resume"]),
        )

    def test_restart_all_stops_resets_and_relaunches_registered_panes(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registrations = [{
            "version": 1, "pane": "%3", "repository": str(self.repo),
            "session": "session-id", "token": "token",
        }]
        calls = []
        resets = []
        function_globals = launcher["restart_all_tmux_sessions"].__globals__
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            function_globals, {
                "tmux_registrations": mock.Mock(side_effect=[registrations, []]),
                "run": lambda arguments, **kwargs: calls.append(arguments),
                "helper": lambda *arguments: resets.append(arguments),
            },
        ):
            self.assertEqual(0, launcher["restart_all_tmux_sessions"]())
        self.assertEqual([("reset", "--repo", str(self.repo))], resets)
        self.assertEqual(3, sum(call[-1] == "C-c" for call in calls))
        literal = next(call for call in calls if "-l" in call)
        self.assertEqual(
            f"cd {shlex.quote(str(self.repo))} && pi --session session-id",
            literal[-1],
        )
        self.assertTrue(any(call[-1] == "Enter" for call in calls))
        self.assertTrue(any(call[:2] == ["tmux", "display-message"] for call in calls))

    def test_tmux_registration_declares_and_clears_pi_command(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(
            codex_arguments=["--session", "session-id"],
            repository=self.repo,
            tmux_pane=None,
            tmux_registration=None,
        )
        calls = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            stdout = state.tmux_registration or ""
            return subprocess.CompletedProcess(arguments, 0, stdout=stdout)

        function_globals = launcher["register_tmux_pane"].__globals__
        with mock.patch.dict(os.environ, {"TMUX_PANE": "%3"}), mock.patch.dict(
            function_globals, {"run": fake_run}
        ):
            launcher["register_tmux_pane"](state)
            launcher["unregister_tmux_pane"](state)

        self.assertIn(
            ["tmux", "set-option", "-p", "-t", "%3", "@codex_sandbox_command", "π"],
            calls,
        )
        self.assertIn(
            ["tmux", "set-option", "-p", "-u", "-t", "%3", "@codex_sandbox_command"],
            calls,
        )

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
        pi_agent = self.home / ".pi/agent"
        result = self.run_launcher("resume", "session-id")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertIn("--cap-drop=ALL", run)
        self.assertIn("--security-opt=no-new-privileges", run)
        self.assertIn(f"type=bind,src={self.repo.resolve()},dst=/src/work,bind-nonrecursive=true", run)
        self.assertIn(f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/work/.git,readonly", run)
        self.assertIn(f"type=bind,src={(self.repo / '.jj').resolve()},dst=/src/work/.jj,readonly", run)
        self.assertIn(
            f"type=bind,src={ROOT / 'config/codex.toml'},"
            "dst=/home/codex/.codex/dotfiles.config.toml,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/codex-developer-instructions.md'},"
            "dst=/home/codex/.codex/developer-instructions.md,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/breq.md'},"
            "dst=/home/codex/.codex/breq.md,readonly",
            run,
        )
        self.assertNotIn(
            f"type=bind,src={pi_agent},dst=/home/codex/.pi/agent",
            run,
        )
        agent_mounts = [
            item for item in run
            if item.endswith("dst=/home/codex/.pi/agent")
        ]
        self.assertEqual(1, len(agent_mounts))
        private_agent = Path(agent_mounts[0].split(",src=", 1)[1].split(",dst=", 1)[0])
        self.assertFalse(private_agent.exists())
        self.assertIn(
            f"type=bind,src={pi_agent / 'sessions'},dst=/home/codex/.pi/agent/sessions",
            run,
        )
        for directory in ("npm", "git"):
            package_store = pi_agent / directory
            self.assertTrue(package_store.is_dir())
            self.assertIn(
                f"type=bind,src={package_store},"
                f"dst=/home/codex/.pi/agent/{directory}",
                run,
            )
            self.assertNotIn(
                f"type=bind,src={package_store},"
                f"dst=/home/codex/.pi/agent/{directory},readonly",
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
                "/home/codex/.pi/agent/breq.md",
                "/home/codex/.pi/agent/coordination-dialect.md",
                "/home/codex/.pi/agent/settings.json",
                "/home/codex/.pi/agent/mcp.json",
                "/home/codex/.pi/agent/keybindings.json",
            ))
        ]
        self.assertEqual(7, len(staged_mounts))
        staged_sources = [
            Path(item.split(",src=", 1)[1].split(",dst=", 1)[0])
            for item in staged_mounts
        ]
        self.assertEqual(1, len({source.parent for source in staged_sources}))
        self.assertTrue(all(not source.is_relative_to(ROOT) for source in staged_sources))
        self.assertIn(
            f"type=bind,src={ROOT / 'config/pi-extensions'},"
            "dst=/home/codex/.pi/agent/pi-extensions,readonly",
            run,
        )
        self.assertNotIn("pi-agent-", " ".join(run))
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertNotIn("EDITOR=/opt/agent-tools/bin/host-editor", run)
        self.assertNotIn("VISUAL=/opt/agent-tools/bin/host-editor", run)
        self.assertTrue(any(item.startswith("CODEX_SANDBOX_EDITOR_ADDRESS=") for item in run))
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", run)
        self.assertFalse(any(item.startswith("CODEX_SANDBOX_EDITOR_TOKEN=") for item in run))
        self.assertFalse(any("dst=/run/host-editor" in item for item in run))
        self.assertLess(run.index("resume"), run.index("session-id"))

        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        self.assertEqual(1, len(snapshots))
        builder = snapshots[0][snapshots[0].index("--jj-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "jj-proxy-image", Path(builder).resolve())

    def test_seeds_offline_model_catalog_without_sharing_guest_writes(self) -> None:
        catalog = self.home / ".pi/agent/models-store.json"
        catalog.parent.mkdir(parents=True)
        contents = '{"openai-codex":{"models":[{"id":"gpt-6-astra"}]}}\n'
        catalog.write_text(contents, encoding="utf-8")
        captured = self.root / "guest-models.json"

        result = self.run_launcher(FAKE_MODEL_STORE_CAPTURE=str(captured))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(contents, captured.read_text(encoding="utf-8"))
        self.assertEqual(contents, catalog.read_text(encoding="utf-8"))

    def test_model_catalog_copy_failure_stops_agent_launch(self) -> None:
        (self.home / ".pi/agent/models-store.json").mkdir(parents=True)

        result = self.run_launcher()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("models-store.json", result.stderr)
        self.assertFalse(any("-it" in call for call in read_calls(self.docker_log)))

    def test_rejects_symlinked_persistent_pi_sessions(self) -> None:
        pi_agent = self.home / ".pi/agent"
        pi_agent.mkdir(parents=True)
        target = self.root / "foreign-sessions"
        target.mkdir()
        (pi_agent / "sessions").symlink_to(target, target_is_directory=True)

        result = self.run_launcher("resume", "session-id")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Pi sessions directory is invalid", result.stderr)

    def test_rejects_symlinked_persistent_pi_package_store(self) -> None:
        pi_agent = self.home / ".pi/agent"
        pi_agent.mkdir(parents=True)
        target = self.root / "foreign-packages"
        target.mkdir()
        (pi_agent / "npm").symlink_to(target, target_is_directory=True)

        result = self.run_launcher("resume", "session-id")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Pi package directory is invalid", result.stderr)

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
            f"type=bind,src={ROOT / 'tools/codex-sandbox/auth-proxy/pi-extension'},"
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
                '"key":"shared-key","image":"sha256:' + '0' * 64 + '"}}'
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

    def test_rejects_cached_auth_sidecar_from_another_network(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher(
            FAKE_SESSION="shared",
            FAKE_SIDECAR_NETWORK="0",
            FAKE_PROXY_STATE=(
                '{"proxies":[],"auth":{"container":"stale-auth-proxy",'
                '"key":"stale-key","image":"sha256:' + '0' * 64 + '"}}'
            ),
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("belongs to another sandbox network", result.stderr)
        calls = read_calls(self.docker_log)
        self.assertFalse(any(call[:1] == ["run"] and "-it" in call for call in calls))
        self.assertTrue(any(
            call[:2] == ["rm", "--force"]
            and any("codex-host-editor-relay-" in item for item in call)
            for call in calls
        ))

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
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertRegex(docker_log, r"rm\t--force\tcodex-sandbox-[0-9]+-[0-9a-f]{12}")
        self.assertIn("codex-host-editor-relay-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertIn("hold-lock", actions)

    def test_timing_names_its_boundary_and_uses_the_full_cleanup_interval(self) -> None:
        builder = self.repo / ".agents" / "sandbox" / "base-image"
        builder.parent.mkdir(parents=True)
        write_executable(builder, "#!/bin/sh\nprintf '%s\\n' node:24-alpine3.22\n")
        result = self.run_launcher(
            CODEX_SANDBOX_TIMING="1", FAKE_CLEANUP_DELAY="0.2",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Sandbox preparation:", result.stderr)
        self.assertIn("base image resolution=", result.stderr)
        self.assertNotIn("Sandbox startup:", result.stderr)
        containers = float(re.search(
            r"Sandbox cleanup: containers=([0-9.]+)s", result.stderr,
        ).group(1))
        total = float(re.search(
            r"Sandbox cleanup total: ([0-9.]+)s", result.stderr,
        ).group(1))
        self.assertGreaterEqual(total, containers)

    def test_creates_network_with_public_only_routes(self) -> None:
        result = self.run_launcher(FAKE_NETWORK_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        creates = [
            call for call in read_calls(self.docker_log)
            if call[:2] == ["network", "create"] and call[-1] == "codex-public-only"
        ]
        self.assertEqual(1, len(creates))
        self.assertIn("--route", creates[0])
        self.assertIn("10.0.0.0/8,prohibit", creates[0])
        self.assertIn("192.168.0.0/16,prohibit", creates[0])

    def test_fresh_build_runs_agent_by_immutable_image_id(self) -> None:
        result = self.run_launcher(FAKE_IMAGE_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        builds = [call for call in read_calls(self.docker_log) if call[:1] == ["build"]]
        self.assertEqual(2, len(builds))
        self.assertTrue(any("tools/codex-sandbox/auth-proxy/Dockerfile" in call for call in builds))
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
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertRegex(docker_log, r"rm\t--force\tcodex-sandbox-[0-9]+-[0-9a-f]{12}")
        self.assertIn("codex-host-editor-relay-", docker_log)
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

    def test_host_editor_relay_is_isolated_and_injected(self) -> None:
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay = next(
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-host-editor-relay-" in item for item in call)
        )
        self.assertIn("--cap-drop=ALL", relay)
        self.assertIn("--security-opt=no-new-privileges", relay)
        self.assertIn("--read-only", relay)
        self.assertIn("--pids-limit", relay)
        self.assertIn("--memory", relay)
        self.assertIn("--cpus", relay)
        self.assertIn("--http-proxy=false", relay)
        self.assertIn("/usr/bin/socat", relay)
        readiness = next(call for call in calls if call[:2] == ["exec", relay[relay.index("--name") + 1]])
        self.assertIn("socket.create_connection", " ".join(readiness))
        self.assertIn("s.recv(4)", " ".join(readiness))
        editor_networks = [
            call for call in calls if call[:2] == ["network", "create"]
            and any("codex-host-editor-" in item for item in call)
        ]
        self.assertEqual(2, len(editor_networks))
        self.assertTrue(any("--internal" in call for call in editor_networks))
        run = self.final_run()
        self.assertTrue(any(item.startswith("CODEX_SANDBOX_EDITOR_ADDRESS=") for item in run))
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", run)
        self.assertFalse(any(item.startswith("CODEX_SANDBOX_EDITOR_TOKEN=") for item in run))

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
        relay_runs = [
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-agent-podman-relay-" in item for item in call)
        ]
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
