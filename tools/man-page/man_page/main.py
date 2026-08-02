"""Resolve manual pages against web providers and launch the first match."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


FALLBACK = 69
LAUNCH_FAILURE = 70
MANPATH_CONFIG = Path("/etc/manpath.config")
INDEX_ENTRY = re.compile(r"^(.*?)\s+\(([^()]*)\)\s+-")


def supported_sections(path: Path = MANPATH_CONFIG) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    for line in lines:
        fields = line.split()
        if fields and fields[0] == "SECTION":
            return set(fields[1:])
    return set()


def parse_request(arguments: list[str], sections: set[str]) -> tuple[str | None, str] | None:
    if len(arguments) == 1:
        return None, arguments[0]
    if len(arguments) == 2 and arguments[0] in sections:
        return arguments[0], arguments[1]
    return None


def probe(url: str) -> bool:
    try:
        with urlopen(Request(url, method="HEAD"), timeout=1) as response:
            return response.status == 200
    except (HTTPError, URLError, OSError, TimeoutError):
        return False


def infer_section(page: str) -> str | None:
    try:
        result = subprocess.run(
            ["man", "-k", "--", page],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except OSError:
        return None
    if result.returncode:
        return None

    matches: set[str] = set()
    for line in result.stdout.splitlines():
        match = INDEX_ENTRY.match(line)
        if match is None:
            continue
        aliases = {alias.strip() for alias in match.group(1).split(",")}
        if page in aliases:
            matches.add(match.group(2))
    if len(matches) == 1:
        return matches.pop()
    return None


def distribution_codename() -> str | None:
    executable = shutil.which("lsb_release")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "-cs"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except OSError:
        return None
    codename = result.stdout.strip()
    return codename if result.returncode == 0 and codename else None


def launch(url: str) -> int:
    executable = shutil.which("xdg-open")
    if executable is None:
        print("xdg-open is required to open a manual page", file=sys.stderr)
        return 127
    try:
        result = subprocess.run([executable, url], check=False)
    except OSError as error:
        print(f"could not launch manual page: {error}", file=sys.stderr)
        return 127
    if result.returncode == 0:
        return 0
    status = result.returncode if result.returncode > 0 else 128 - result.returncode
    return LAUNCH_FAILURE if status == FALLBACK else status


def resolve(arguments: list[str]) -> int:
    request = parse_request(arguments, supported_sections())
    if request is None:
        return FALLBACK
    section, page = request
    encoded_page = quote(page, safe="")
    encoded_section = quote(section, safe="") if section is not None else None

    openbsd = f"https://man.openbsd.org/{encoded_page}"
    if encoded_section is not None:
        openbsd += f".{encoded_section}"
    if probe(openbsd):
        return launch(openbsd)

    resolved_section = section if section is not None else infer_section(page)
    codename = distribution_codename()
    if resolved_section is None or codename is None:
        return FALLBACK
    encoded_section = quote(resolved_section, safe="")
    ubuntu = (
        "https://manpages.ubuntu.com/manpages/"
        f"{quote(codename, safe='')}/man{encoded_section}/"
        f"{encoded_page}.{encoded_section}.html"
    )
    if probe(ubuntu):
        return launch(ubuntu)
    return FALLBACK


def main(arguments: list[str]) -> int:
    try:
        return resolve(arguments)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
