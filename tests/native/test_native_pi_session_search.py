"""Run the maintained session-search suite against the installed Pi consumer."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/pi-session-search"


def test_pi_session_search(run_native_suite):
    # npm pack is part of the native suite. Keep every generated artifact and
    # dependency link in a disposable copy, never the authoritative package.
    sdk_path = os.environ.get("PI_PACKAGE_DIR")
    assert sdk_path, "set PI_PACKAGE_DIR to the installed @earendil-works/pi-coding-agent directory"
    sdk = Path(sdk_path).resolve()
    manifest = json.loads((sdk / "package.json").read_text())
    assert manifest["name"] == "@earendil-works/pi-coding-agent"
    # Resolve the peer beside Pi, not through dotfiles' older unit-test SDK.
    typebox = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import {createRequire} from 'node:module'; "
         "console.log(createRequire(process.argv[1]).resolve('typebox'))",
         str(sdk / "package.json")],
        check=True, capture_output=True, text=True,
    )
    # TypeBox exports its entry point but not package.json. Find the owning
    # manifest from that resolved entry rather than bypassing package exports.
    typebox_package = next(
        parent for parent in Path(typebox.stdout.strip()).resolve().parents
        if (parent / "package.json").is_file()
        and json.loads((parent / "package.json").read_text()).get("name") == "typebox"
    )
    with tempfile.TemporaryDirectory(prefix="dotfiles-pi-session-search-") as temporary:
        package = Path(temporary) / "pi-session-search"
        shutil.copytree(SOURCE, package, ignore=shutil.ignore_patterns(
            "node_modules", "dist", "work", "target", "*.tgz",
        ))
        modules = package / "node_modules"
        (modules / "@earendil-works").mkdir(parents=True)
        (modules / "@earendil-works/pi-coding-agent").symlink_to(sdk, target_is_directory=True)
        (modules / "typebox").symlink_to(typebox_package, target_is_directory=True)
        run_native_suite(["npm", "--prefix", str(package), "test"])
