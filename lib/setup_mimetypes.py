#!/usr/bin/env python3

import argparse
import json
import os
import plistlib
from pathlib import Path


def read_lines(path: Path) -> set[str]:
    try:
        return {
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }
    except FileNotFoundError:
        return set()


def discover_editor_mimes(policy: dict, mime_directories: list[Path]) -> list[str]:
    known: set[str] = set()
    parents: dict[str, set[str]] = {}
    for directory in mime_directories:
        known.update(read_lines(directory / "types"))
        for relation in read_lines(directory / "subclasses"):
            try:
                child, parent = relation.split()
            except ValueError:
                continue
            known.add(child)
            known.add(parent)
            parents.setdefault(child, set()).add(parent)

    roots = set(policy["editor_mime_roots"])
    prefixes = tuple(policy["editor_mime_prefixes"])
    editor_mimes = set(policy["editor_mime_exceptions"])
    editor_mimes.update(mime for mime in known if mime.startswith(prefixes))

    descendants = set(roots)
    changed = True
    while changed:
        changed = False
        for child, direct_parents in parents.items():
            if child not in descendants and direct_parents & descendants:
                descendants.add(child)
                changed = True
    editor_mimes.update(descendants)
    return sorted(editor_mimes)


def default_mime_directories() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_directories = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    return [
        data_home / "mime",
        *(Path(entry) / "mime" for entry in data_directories.split(":")),
    ]


def write_linux_desktop(template: Path, destination: Path, mimes: list[str]) -> None:
    lines = template.read_text().splitlines()
    mime_line = "MimeType=" + ";".join(mimes) + ";"
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("MimeType="):
            lines[index] = mime_line
            replaced = True
            break
    if not replaced:
        lines.append(mime_line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n")


def write_macos_app(app: Path, policy: dict) -> None:
    contents = app / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    extension_utis = [
        f"dev.jyn.source-code.{extension.replace('_', '-')}"
        for extension in policy["editor_extension_exceptions"]
    ]
    plist = {
        "CFBundleDisplayName": "Neovim",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Text document",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [*policy["editor_utis"], *extension_utis],
            }
        ],
        "CFBundleExecutable": "nvim-launcher",
        "CFBundleIdentifier": "dev.jyn.nvim",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Neovim",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,
        "UTImportedTypeDeclarations": [
            {
                "UTTypeConformsTo": ["public.source-code", "public.text"],
                "UTTypeDescription": f"{extension} source code",
                "UTTypeIdentifier": identifier,
                "UTTypeTagSpecification": {
                    "public.filename-extension": [extension]
                },
            }
            for extension, identifier in zip(
                policy["editor_extension_exceptions"], extension_utis
            )
        ],
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(plist, output, sort_keys=False)

    (contents / "launcher.swift").write_text(
        """import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        for filename in filenames {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["hx-hax", filename]
            try? process.run()
        }
        sender.reply(toOpenOrPrint: .success)
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
"""
    )


def load_policy(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    linux = subparsers.add_parser("linux")
    linux.add_argument("--mime-dir", action="append", type=Path, default=[])
    linux.add_argument("--desktop-template", type=Path)
    linux.add_argument("--desktop-output", type=Path)
    macos = subparsers.add_parser("macos-app")
    macos.add_argument("app", type=Path)
    arguments = parser.parse_args()
    policy = load_policy(arguments.policy)

    if arguments.command == "linux":
        mime_directories = arguments.mime_dir or default_mime_directories()
        mimes = discover_editor_mimes(policy["linux"], mime_directories)
        if bool(arguments.desktop_template) != bool(arguments.desktop_output):
            parser.error("--desktop-template and --desktop-output must be used together")
        if arguments.desktop_template:
            write_linux_desktop(
                arguments.desktop_template, arguments.desktop_output, mimes
            )
        for mime in mimes:
            print(mime)
    else:
        write_macos_app(arguments.app, policy["macos"])


if __name__ == "__main__":
    main()
