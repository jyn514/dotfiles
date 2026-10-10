#!/usr/bin/env python3

import json
import os
from pathlib import Path
import sys
import tarfile


command = sys.argv[1]
package = Path(sys.argv[2])
capture = Path(os.environ["CAPTURE"])
commands = json.loads(capture.read_text())["commands"] if capture.exists() else []
commands.append(command)
capture.write_text(json.dumps({
    "commands": commands,
    "arguments": sys.argv[1:2] + sys.argv[3:],
    "package": str(package),
    "readme": (package / "README.md").read_text(),
    "has_manifest": (package / "package.json").is_file(),
    "has_license": (package / "LICENSE").is_file(),
    "has_codex_plugin": (package / ".codex-plugin/plugin.json").is_file(),
    "has_claude_plugin": (package / ".claude-plugin/plugin.json").is_file(),
    "has_claude_marketplace": (package / ".claude-plugin/marketplace.json").is_file(),
    "has_skills": (package / "skills").is_dir(),
    "reference_files": {
        str(path.relative_to(package)): path.read_text(encoding="utf-8")
        for path in (package / "skills").rglob("references/*.md")
    },
}), encoding="utf-8")

status = int(os.environ.get("FAKE_NPM_EXIT", "0"))
if status:
    print("fixture npm failure", file=sys.stderr)
    raise SystemExit(status)
if command == "pack":
    files = [path for path in package.rglob("*") if path.is_file()]
    omitted = os.environ.get("FAKE_NPM_OMIT", "")
    filename = "fixture.tgz"
    with tarfile.open(package / filename, "w:gz") as archive:
        for path in files:
            relative = path.relative_to(package).as_posix()
            if relative != omitted:
                archive.add(path, arcname=f"package/{relative}")
    manifest = json.loads((package / "package.json").read_text())
    if os.environ.get("FAKE_NPM_BAD_JSON"):
        print("not JSON")
    else:
        print(json.dumps([{
            "filename": filename,
            "name": manifest["name"],
            "version": manifest["version"],
        }]))
