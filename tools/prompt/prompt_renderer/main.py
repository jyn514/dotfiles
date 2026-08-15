"""Collect prompt facts and emit complete target-specific prompt bytes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import unicodedata

from .jujutsu import parse_log as parse_jj_log
from .jujutsu import QUERY as JJ_QUERY


ESCAPE = "\x1b"
COLORS = {
    "red": f"{ESCAPE}[0;31m",
    "green": f"{ESCAPE}[0;32m",
    "reset": f"{ESCAPE}[0;0m",
    "faint-green": f"{ESCAPE}[2;32m",
    "faint-white": f"{ESCAPE}[2;37m",
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class Repository:
    color: str
    label: str = ""
    jj_description: str | None = None


@dataclass(frozen=True)
class Facts:
    label: str
    host: str
    path: str
    repository: Repository | None
    ssh: bool
    root: bool


class Style:
    def __init__(self, target: str) -> None:
        self.target = target

    def color(self, name: str) -> str:
        sequence = COLORS[name]
        if self.target == "bash":
            return f"\\[{sequence}\\]"
        if self.target == "zsh":
            return f"%{{{sequence}%}}"
        if self.target in ("fish-left", "fish-right"):
            return sequence
        return ""


def visible_width(value: str) -> int:
    plain = ANSI.sub("", value).replace("\\[", "").replace("\\]", "")
    plain = plain.replace("%{", "").replace("%}", "")
    width = 0
    for character in plain:
        if unicodedata.combining(character) or unicodedata.category(character).startswith("C"):
            continue
        width += 2 if unicodedata.east_asian_width(character) in ("F", "W") else 1
    return width


def terminal_text(value: str) -> str:
    """Render data visibly without allowing it to inject terminal controls."""
    output: list[str] = []
    for character in value:
        codepoint = ord(character)
        if 0xDC80 <= codepoint <= 0xDCFF:
            output.append(f"\\x{codepoint - 0xDC00:02x}")
        elif character == "\n":
            output.append("\\n")
        elif character == "\r":
            output.append("\\r")
        elif character == "\t":
            output.append("\\t")
        elif unicodedata.category(character).startswith("C"):
            width = 4 if codepoint <= 0xFFFF else 8
            output.append(f"\\u{codepoint:0{width}x}")
        else:
            output.append(character)
    return "".join(output)


def display_path(cwd: Path, home: Path | None, trim: int = 2) -> str:
    value = os.fsdecode(os.fsencode(cwd))
    if home is not None:
        home_value = os.fsdecode(os.fsencode(home))
        if value == home_value:
            value = "~"
        elif value.startswith(home_value + os.sep):
            value = "~" + value[len(home_value) :]
    prefix = "~/" if value.startswith("~/") else os.sep if value.startswith(os.sep) else ""
    remainder = value[len(prefix) :]
    parts = remainder.split(os.sep) if remainder else []
    if len(parts) > trim:
        value = prefix + "..." + os.sep + os.sep.join(parts[-trim:])
    return value


def os_release_id(path: Path = Path("/etc/os-release")) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        name, separator, raw = line.partition("=")
        if separator and name == "ID":
            try:
                values = shlex.split(raw, comments=False, posix=True)
            except ValueError:
                return ""
            return values[0] if len(values) == 1 else ""
    return ""


def host_label(os_release: Path = Path("/etc/os-release")) -> str:
    container = os.environ.get("container", "")
    if not container:
        return socket.gethostname()
    system = os_release_id(os_release)
    return f"{container}:{system}" if system else container


def run(arguments: list[bytes], *, timeout: float = 0.2) -> subprocess.CompletedProcess[bytes] | None:
    environment = os.environb.copy() if hasattr(os, "environb") else None
    if environment is not None:
        environment[b"GIT_OPTIONAL_LOCKS"] = b"0"
    try:
        return subprocess.run(
            arguments,
            check=False,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def jj_workspace(cwd: Path) -> bool:
    candidate = cwd
    while True:
        if (candidate / ".jj").exists():
            return True
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent


def jj_description() -> tuple[str, str] | None:
    result = run(JJ_QUERY, timeout=0.2)
    if result is None or result.returncode:
        return None
    parsed = parse_jj_log(result.stdout)
    if parsed is None:
        return None
    current_empty, description = parsed
    return ("faint-green" if current_empty else "red", description)


def git_repository(cwd: Path) -> Repository | None:
    is_jj = jj_workspace(cwd)
    if is_jj:
        jj = jj_description()
        if jj is not None:
            return Repository(jj[0], jj_description=jj[1])

    in_git = run([b"git", b"rev-parse", b"--git-dir"])
    if in_git is None or in_git.returncode:
        return None

    changed = run([
        b"git",
        b"diff-index",
        b"--name-only",
        b"--quiet",
        b"--ignore-submodules",
        b"HEAD",
        b"--",
    ])
    color = "faint-green"
    if changed is None or changed.returncode:
        head = run([b"git", b"rev-parse", b"--verify", b"HEAD"])
        if head is not None and head.returncode == 0:
            color = "red"

    branch = run([b"git", b"symbolic-ref", b"--short", b"HEAD"])
    if branch is not None and branch.returncode == 0:
        return Repository(color, os.fsdecode(branch.stdout).replace("\n", ""))

    tags = run([b"git", b"tag", b"--points-at", b"HEAD"])
    if tags is not None and tags.returncode == 0 and tags.stdout:
        return Repository(color, os.fsdecode(tags.stdout).replace("\n", ""))

    remotes = run([
        b"git",
        b"for-each-ref",
        b"--points-at",
        b"HEAD",
        b"--format=%(refname:short)",
        b"refs/remotes",
    ])
    if remotes is not None and remotes.returncode == 0:
        for remote in remotes.stdout.splitlines():
            if b"/gh-readonly-queue/" not in remote:
                return Repository(color, os.fsdecode(remote))

    locals_ = run([
        b"git",
        b"for-each-ref",
        b"--points-at",
        b"HEAD",
        b"--format=%(refname:short)",
        b"refs/heads",
    ])
    if locals_ is not None and locals_.returncode == 0 and locals_.stdout:
        name = os.fsdecode(locals_.stdout.splitlines()[0])
        return Repository(color, f"(detached at {name})")
    return Repository(color, "(detached HEAD)")


def collect(label: str, cwd: Path | None = None, os_release: Path = Path("/etc/os-release")) -> Facts:
    directory = cwd or Path.cwd()
    home_value = os.environ.get("HOME")
    return Facts(
        label=Path(label).name,
        host=host_label(os_release),
        path=display_path(directory, Path(home_value) if home_value else None),
        repository=git_repository(directory),
        ssh=bool(os.environ.get("SSH_TTY")),
        root=hasattr(os, "geteuid") and os.geteuid() == 0,
    )


def repository_plain(repository: Repository | None) -> str:
    if repository is None:
        return ""
    if repository.jj_description is not None:
        return f" (jj: {terminal_text(repository.jj_description)})"
    return f" {terminal_text(repository.label)}"


def render_repository(repository: Repository | None, style: Style) -> str:
    if repository is None:
        return ""
    color = style.color(repository.color)
    if repository.jj_description is not None:
        faint = style.color("faint-white")
        reset = style.color("reset")
        description = terminal_text(repository.jj_description)
        return f" {faint}({color}jj{faint}: {reset}{description}{faint})"
    return f" {color}{terminal_text(repository.label)}"


def render_left(
    facts: Facts,
    target: str,
    last_status: int,
    columns: int,
    *,
    vscode: bool = False,
) -> str:
    style = Style(target)
    faint = style.color("faint-white")
    red = style.color("red")
    reset = style.color("reset")
    label = terminal_text(facts.label)
    host = terminal_text(facts.host)
    path = terminal_text(facts.path)
    identity_plain = f"({label}@{host}"
    identity = f"{faint}({label}@{host}"
    if facts.ssh:
        identity_plain += "[ssh]"
        identity += f"{red}[ssh]"
    if facts.root:
        identity_plain += ",root"
        identity += f"{reset},{red}root"
    identity_plain += ")"
    identity += f"{faint})"
    location_plain = path + repository_plain(facts.repository)
    location = f"{faint}{path}{render_repository(facts.repository, style)}"
    separator = " "
    if columns > 0 and visible_width(identity_plain + " " + location_plain) > columns:
        separator = "\n"
    header = f"{identity}{separator}{location}\n"
    if vscode:
        return header + reset
    command_color = style.color("green" if last_status == 0 else "red")
    return f"{header}{command_color}; {reset}"


def duration_seconds(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.2f}".rstrip("0").rstrip(".")


def render_right(duration_ms: int, timestamp: str) -> str:
    style = Style("fish-right")
    if timestamp:
        return f"{style.color('faint-white')}{terminal_text(timestamp)}"
    if duration_ms > 99:
        return f"{style.color('faint-white')}+{duration_seconds(duration_ms)}s"
    return ""


def render_claude(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("Claude input must be a JSON object")
    workspace = data.get("workspace")
    cwd_value = workspace.get("current_dir") if isinstance(workspace, dict) else None
    if not cwd_value:
        cwd_value = data.get("cwd")
    if cwd_value is not None and not isinstance(cwd_value, str):
        raise ValueError("Claude working directory must be a string")
    model = data.get("model")
    label = model.get("display_name", "claude") if isinstance(model, dict) else "claude"
    if not isinstance(label, str):
        raise ValueError("Claude model name must be a string")
    context = data.get("context_window")
    used = context.get("used_percentage") if isinstance(context, dict) else None
    if used is not None and not isinstance(used, (int, float)):
        raise ValueError("Claude context percentage must be numeric")
    cwd = Path(cwd_value) if cwd_value else Path.cwd()
    if not cwd.is_dir():
        raise ValueError(f"Claude working directory is unavailable: {cwd}")
    previous = Path.cwd()
    try:
        os.chdir(cwd)
        facts = collect(label, cwd)
    finally:
        os.chdir(previous)
    prefix = f" ctx:{used:.0f}% " if used is not None else ""
    label_text = terminal_text(facts.label)
    host_text = terminal_text(facts.host)
    path_text = terminal_text(facts.path)
    return f"{prefix}({label_text}@{host_text}) {path_text}{repository_plain(facts.repository)}"


def integer(value: str, name: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    return result


def main(arguments: list[str]) -> int:
    try:
        if arguments == ["claude"]:
            data = json.load(sys.stdin)
            output = render_claude(data)
        elif arguments and arguments[0] in ("bash", "zsh", "fish-left", "fish-right"):
            if len(arguments) < 3:
                raise ValueError("interactive targets require status and duration-ms")
            target = arguments[0]
            status = integer(arguments[1], "status")
            duration = integer(arguments[2], "duration-ms")
            if duration < 0:
                raise ValueError("duration-ms must not be negative")
            if target == "fish-right":
                timestamp = arguments[3] if len(arguments) == 4 else ""
                if len(arguments) > 4:
                    raise ValueError("fish-right accepts at most one timestamp")
                output = render_right(duration, timestamp)
            else:
                label = arguments[3] if len(arguments) == 4 else target.removesuffix("-left")
                if len(arguments) > 4:
                    raise ValueError(f"{target} accepts at most one shell label")
                output = render_left(
                    collect(label),
                    target,
                    status,
                    int(os.environ.get("COLUMNS", "0")),
                    vscode=os.environ.get("VSCODE_SHELL_INTEGRATION") == "1",
            )
        else:
            raise ValueError(
                "usage: prompt-command claude | prompt-command "
                "<bash|zsh|fish-left|fish-right> <status> <duration-ms>"
            )
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"prompt-command: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(output)
    return 0
