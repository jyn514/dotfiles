#!/usr/bin/env python3
"""Regenerate the pinned Dashboard runtime and complete source patches.

Run only on an owned source checkout and an extracted published web package.
Dependencies/builds remain upstream's responsibility; installation never runs this.

Reproduce in a disposable checkout at BASE (no installed-package editing):
  pnpm install --frozen-lockfile
  patch --batch --fuzz=0 -p1 < /path/to/pi-dashboard-0.11.0-source.patch
  NODE_OPTIONS=--max-old-space-size=4096 npm run build
  python3 /path/to/regenerate_pi_dashboard_patch.py --source "$PWD" \
      --published-web-dist /path/to/extracted-pi-dashboard-web-0.11.0/dist

The comparison base is package/dist from the published
@blackbelt-technology/pi-dashboard-web@0.11.0 npm archive, NOT another local
build. Output is a complete source/test companion and a runtime source + native
Vite overlay. Keep obsolete hashed assets. The installer maps the client workspace
path to the resolved web package's dist and refreshes gzip sidecars; gzip bytes
are intentionally not embedded in this patch. Build warnings/chunk churn are not
permission to surgically rewrite private minified symbols instead.

"""

import argparse
import difflib
from pathlib import Path
import subprocess

BASE = "f93a27812534b2c1e2465dff52172fa763d631dd"


def git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(source), *args])


def lines(text: str) -> list[str]:
    # Native patch counts LF, not Unicode line separators inside bundled JS.
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def diff(before: bytes, after: bytes, name: str, added: bool = False) -> str:
    output = []
    for line in difflib.unified_diff(
        lines(before.decode("utf-8")),
        lines(after.decode("utf-8")),
        fromfile="/dev/null" if added else "a/" + name,
        tofile="b/" + name,
        n=3,
    ):
        output.append(line)
        if not line.endswith("\n"):
            output.append("\n\\ No newline at end of file\n")
    return "".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--published-web-dist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    source = args.source.resolve()
    published = args.published_web_dist.resolve()
    output = args.output_dir.resolve()
    if git(source, "rev-parse", "HEAD").decode().strip() != BASE:
        raise SystemExit("Source HEAD must be the reviewed published 0.11.0 commit")
    built = source / "packages/client/dist"
    if not (built / "index.html").is_file() or not (published / "index.html").is_file():
        raise SystemExit("Build source first; provide the extracted published web dist")
    runtime = [f"# Dashboard 0.11.0; upstream {BASE}\n"]
    whole_source = [f"# Complete source/test changes against Dashboard 0.11.0 {BASE}\n"]
    changed = git(source, "diff", "--name-only", "HEAD").decode().splitlines()
    additions = git(source, "ls-files", "--others", "--exclude-standard").decode().splitlines()
    for name in sorted(set(changed + additions)):
        if not name.startswith("packages/") or "/src/" not in name:
            raise SystemExit(f"Unexpected source change: {name}")
        added = name in additions
        before = b"" if added else git(source, "show", f"HEAD:{name}")
        after = (source / name).read_bytes()
        change = diff(before, after, name, added)
        whole_source.append(change)
        if not name.startswith("packages/client/") and "/__tests__/" not in name:
            runtime.append(change)
    assets = 0
    for file in sorted(built.rglob("*")):
        if not file.is_file() or file.suffix in {".gz", ".br"} or file.name == "AGENTS.md":
            continue
        relative = file.relative_to(built)
        original = published / relative
        added = not original.exists()
        before = b"" if added else original.read_bytes()
        after = file.read_bytes()
        if before == after:
            continue
        runtime.append(diff(before, after, "packages/client/dist/" + relative.as_posix(), added))
        assets += 1
    # Keep obsolete hashed assets. Only the native build's entrypoint/import graph
    # becomes active; deleting old unreferenced assets adds unnecessary patch churn.
    output.mkdir(parents=True, exist_ok=True)
    (output / "pi-dashboard-0.11.0.patch").write_text("".join(runtime), encoding="utf-8")
    (output / "pi-dashboard-0.11.0-source.patch").write_text("".join(whole_source), encoding="utf-8")
    print(f"Wrote runtime patch ({assets} native build assets) and complete source/test patch")


if __name__ == "__main__":
    main()
