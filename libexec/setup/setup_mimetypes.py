#!/usr/bin/env python3

import argparse
import json
import os
import plistlib
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "lib/mimetypes.json"
BUNDLE_ID = "dev.jyn.nvim"
MANAGED_UTI_PREFIXES = (
    "dev.jyn.nvim.document.",
    "dev.jyn.plain-text.",
    "dev.jyn.source-code.",
)
LAUNCH_SERVICES_DOMAIN = (
    "com.apple.LaunchServices/com.apple.launchservices.secure"
)
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


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


def read_macos_handler_utis(path: Path) -> list[str]:
    with path.open("rb") as input_file:
        preferences = plistlib.load(input_file)
    handlers = preferences.get("LSHandlers", [])
    return sorted(
        {
            content_type
            for handler in handlers
            if isinstance(handler, dict)
            if isinstance(content_type := handler.get("LSHandlerContentType"), str)
        }
    )


def remove_macos_bundle_handlers(
    preferences: dict, bundle_id: str, keep_utis: set[str] | None = None
) -> dict:
    keep_utis = keep_utis or set()
    handlers = []
    for original in preferences.get("LSHandlers", []):
        if not isinstance(original, dict):
            handlers.append(original)
            continue
        if original.get("LSHandlerContentType") in keep_utis:
            handler = original
        else:
            handler = {
                key: value
                for key, value in original.items()
                if not (key.startswith("LSHandlerRole") and value == bundle_id)
            }
        if any(key.startswith("LSHandlerRole") for key in handler):
            handlers.append(handler)
    preferences["LSHandlers"] = handlers
    return preferences


def clean_macos_preferences(
    source: Path,
    destination: Path,
    bundle_id: str,
    keep_utis: set[str] | None = None,
) -> None:
    with source.open("rb") as input_file:
        preferences = plistlib.load(input_file)
    remove_macos_bundle_handlers(preferences, bundle_id, keep_utis)
    with destination.open("wb") as output:
        plistlib.dump(preferences, output, sort_keys=False)


def write_macos_app(
    app: Path,
    *,
    name: str,
    bundle_id: str,
    command: list[str],
    role: str,
    utis: list[str],
    launcher_source: Path,
    declared_extensions: list[str] | None = None,
    declared_parent: str = "public.data",
) -> None:
    contents = app / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    declared_extensions = declared_extensions or []
    extension_utis = [
        managed_extension_uti(bundle_id, extension) for extension in declared_extensions
    ]
    plist = {
        "CFBundleDisplayName": name,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": f"{name} document",
                "CFBundleTypeRole": role,
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [*utis, *extension_utis],
            }
        ],
        "CFBundleExecutable": "file-handler",
        "CFBundleIdentifier": bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "JynCommand": command,
        "LSUIElement": True,
        "UTExportedTypeDeclarations": [
            {
                "UTTypeConformsTo": [declared_parent],
                "UTTypeDescription": f"{extension} {name} document",
                "UTTypeIdentifier": identifier,
                "UTTypeTagSpecification": {
                    "public.filename-extension": [extension]
                },
            }
            for extension, identifier in zip(
                declared_extensions, extension_utis
            )
        ],
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(plist, output, sort_keys=False)

    shutil.copyfile(launcher_source, contents / "launcher.swift")


def load_policy(path: Path) -> dict:
    return json.loads(path.read_text())


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def linux_setup(policy: dict, dry_run: bool) -> None:
    mimes = discover_editor_mimes(
        policy["linux"], default_mime_directories()
    )
    desktop = Path.home() / ".local/share/applications/nvim-generated.desktop"
    if dry_run:
        print("Neovim MIME defaults:")
        for mime in mimes:
            print(f"  {mime}")
    else:
        write_linux_desktop(ROOT / "config/nvim.desktop", desktop, mimes)
        if command_exists("update-desktop-database"):
            run(["update-desktop-database", str(desktop.parent)])
        for mime in mimes:
            run(["xdg-mime", "default", desktop.name, mime])

    if command_exists("fx"):
        if dry_run:
            print("fx MIME defaults:")
            print("  application/json")
        else:
            run(
                [
                    "xdg-mime",
                    "default",
                    "fx-usercreated-1.desktop",
                    "application/json",
                ]
            )

    if command_exists("xdg-settings"):
        browser = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            check=False,
            text=True,
            capture_output=True,
        ).stdout.strip()
        if browser:
            if dry_run:
                print(f"Browser MIME defaults ({browser}):")
                print("  image/svg+xml")
            else:
                run(["xdg-mime", "default", browser, "image/svg+xml"])


def export_launch_services(path: Path) -> bool:
    with path.open("wb") as output:
        result = subprocess.run(
            ["defaults", "export", LAUNCH_SERVICES_DOMAIN, "-"],
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return result.returncode == 0


def bundle_handler_roles(
    preferences: dict, bundle_id: str
) -> list[tuple[str, str]]:
    associations = []
    for handler in preferences.get("LSHandlers", []):
        if not isinstance(handler, dict):
            continue
        content_type = handler.get("LSHandlerContentType", "<unknown type>")
        for key, value in handler.items():
            if key.startswith("LSHandlerRole") and value == bundle_id:
                associations.append((content_type, key.removeprefix("LSHandlerRole")))
    return sorted(associations)


def compile_launcher(output: Path) -> None:
    run(
        [
            "xcrun",
            "swiftc",
            str(ROOT / "libexec/setup/file-handler.swift"),
            "-o",
            str(output),
        ]
    )


def terminate_running_handler(app: Path) -> None:
    executable = str(app / "Contents/MacOS/file-handler")
    processes = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=False,
        text=True,
        capture_output=True,
    )
    for line in processes.stdout.splitlines():
        try:
            pid_text, command = line.strip().split(maxsplit=1)
        except ValueError:
            continue
        if command == executable or command.startswith(executable + " "):
            try:
                os.kill(int(pid_text), signal.SIGTERM)
            except ProcessLookupError:
                pass


def filter_source_utis(classifier: Path, utis: list[str]) -> list[str]:
    result = run(
        [str(classifier), "--filter-source-utis"],
        input="".join(f"{uti}\n" for uti in utis),
        text=True,
        capture_output=True,
    )
    return sorted(
        uti
        for uti in set(result.stdout.splitlines())
        if not uti.startswith(MANAGED_UTI_PREFIXES)
    )


def resolve_extension_utis(
    classifier: Path, extensions: list[str]
) -> dict[str, str]:
    result = run(
        [str(classifier), "--extension-utis"],
        input="".join(f"{extension}\n" for extension in extensions),
        text=True,
        capture_output=True,
    )
    resolved = {}
    for line in result.stdout.splitlines():
        extension, uti = line.split("\t", 1)
        if not uti.startswith(MANAGED_UTI_PREFIXES):
            resolved[extension] = uti
    return resolved


def missing_uti_defaults(
    utis: list[str], current_defaults: dict[str, str], bundle_id: str
) -> list[str]:
    return sorted(uti for uti in utis if current_defaults.get(uti) != bundle_id)


def missing_extension_defaults(
    extensions: list[str], current_defaults: dict[str, str], bundle_id: str
) -> list[str]:
    return sorted(
        extension
        for extension in extensions
        if current_defaults.get(extension) != bundle_id
    )


def managed_extension_uti(bundle_id: str, extension: str) -> str:
    return f"{bundle_id}.document.{extension.replace('_', '-')}"


def role_defaults(preferences: dict, utis: list[str], role: str) -> dict[str, str]:
    defaults = {}
    role_key = f"LSHandlerRole{role}"
    for handler in preferences.get("LSHandlers", []):
        if not isinstance(handler, dict):
            continue
        content_type = handler.get("LSHandlerContentType")
        if content_type not in utis:
            continue
        default = handler.get(role_key) or handler.get("LSHandlerRoleAll")
        if isinstance(default, str):
            defaults[content_type] = default
    return defaults


def extension_defaults(
    classifier: Path, probe_directory: Path, extensions: list[str]
) -> dict[str, str]:
    probe_directory.mkdir()
    probes = {extension: probe_directory / f"probe.{extension}" for extension in extensions}
    for probe in probes.values():
        probe.touch()
    result = run(
        [str(classifier), "--file-defaults"],
        input="".join(f"{probe}\n" for probe in probes.values()),
        text=True,
        capture_output=True,
    )
    defaults_by_path = dict(line.split("\t", 1) for line in result.stdout.splitlines())
    return {
        extension: defaults_by_path.get(str(probe), "")
        for extension, probe in probes.items()
    }


def validate_macos_policy(policy: dict) -> None:
    editor_extensions = set(policy["editor_extensions"])
    ambiguous_extensions = set(policy["editor_ambiguous_extensions"])
    json_extensions = set(policy["json_handler"]["extensions"])
    if unknown := ambiguous_extensions - editor_extensions:
        raise RuntimeError(
            "ambiguous extensions are not editor-owned: " + ", ".join(sorted(unknown))
        )
    if overlap := editor_extensions & json_extensions:
        raise RuntimeError(
            "extensions are owned by both nvim and fx: " + ", ".join(sorted(overlap))
        )


def macos_setup(policy: dict, dry_run: bool) -> None:
    validate_macos_policy(policy["macos"])
    required_commands = ("duti", "xcrun")
    missing = [
        command for command in required_commands if not command_exists(command)
    ]
    if missing:
        raise RuntimeError(f"missing required command: {', '.join(missing)}")

    with tempfile.TemporaryDirectory(prefix="setup-mimetypes.") as temporary:
        temporary_directory = Path(temporary)
        preferences_path = temporary_directory / "handlers.plist"
        clean_path = temporary_directory / "handlers-clean.plist"
        classifier = temporary_directory / "file-handler"
        preferences_available = export_launch_services(preferences_path)
        if preferences_available:
            with preferences_path.open("rb") as input_file:
                preferences = plistlib.load(input_file)
        else:
            print(
                "warning: could not inspect existing Launch Services associations",
                file=sys.stderr,
            )
            preferences = {"LSHandlers": []}
            with preferences_path.open("wb") as output:
                plistlib.dump(preferences, output)

        compile_launcher(classifier)
        registered_utis = read_macos_handler_utis(preferences_path)
        source_utis = filter_source_utis(classifier, registered_utis)
        explicit_utis = policy["macos"]["editor_utis"]
        extensions = policy["macos"]["editor_extensions"]
        ambiguous_extensions = set(policy["macos"]["editor_ambiguous_extensions"])
        json_handler = policy["macos"]["json_handler"]
        json_extensions = json_handler["extensions"]
        extension_utis = resolve_extension_utis(
            classifier, [*extensions, *json_extensions]
        )
        existing_roles = bundle_handler_roles(preferences, BUNDLE_ID)
        managed_extension_utis = {
            extension: managed_extension_uti(BUNDLE_ID, extension)
            for extension in extensions
        }
        claimed_extension_utis = {
            uti
            for extension, uti in extension_utis.items()
            if extension not in ambiguous_extensions
        }
        desired_utis = set(
            [
                *explicit_utis,
                *source_utis,
                *claimed_extension_utis,
                *managed_extension_utis.values(),
            ]
        )
        stale_roles = [
            role for role in existing_roles if role[0] not in desired_utis
        ]
        current_uti_defaults = role_defaults(
            preferences, [*explicit_utis, *source_utis], "Editor"
        )
        current_extension_defaults = extension_defaults(
            classifier, temporary_directory / "editor-probes", extensions
        )
        missing_utis = missing_uti_defaults(
            [*explicit_utis, *source_utis], current_uti_defaults, BUNDLE_ID
        )
        missing_extensions = missing_extension_defaults(
            extensions, current_extension_defaults, BUNDLE_ID
        )
        json_bundle_id = json_handler["bundle_id"]
        json_existing_roles = bundle_handler_roles(preferences, json_bundle_id)
        json_desired_utis = set(
            [
                *json_handler["utis"],
                *(
                    extension_utis[extension]
                    for extension in json_extensions
                    if extension in extension_utis
                ),
            ]
        )
        json_stale_roles = [
            role for role in json_existing_roles if role[0] not in json_desired_utis
        ]
        json_current_uti_defaults = role_defaults(
            preferences, json_handler["utis"], json_handler["role"]
        )
        json_current_extension_defaults = extension_defaults(
            classifier, temporary_directory / "json-probes", json_extensions
        )
        json_missing_utis = missing_uti_defaults(
            json_handler["utis"], json_current_uti_defaults, json_bundle_id
        )
        json_missing_extensions = missing_extension_defaults(
            json_extensions,
            json_current_extension_defaults,
            json_bundle_id,
        )

        if dry_run:
            print("Remove existing Neovim handler roles:")
            if stale_roles:
                for content_type, role in stale_roles:
                    print(f"  {content_type} ({role or 'All'})")
            else:
                print("  (none)")
            print("Register Neovim UTIs:")
            if missing_utis:
                for uti in missing_utis:
                    print(f"  {uti}")
            else:
                print("  (none)")
            print("Register Neovim extensions:")
            if missing_extensions:
                for extension in missing_extensions:
                    print(f"  .{extension}")
            else:
                print("  (none)")
            print("Remove existing fx handler roles:")
            if json_stale_roles:
                for content_type, role in json_stale_roles:
                    print(f"  {content_type} ({role or 'All'})")
            else:
                print("  (none)")
            print("Register fx UTIs:")
            if json_missing_utis:
                for uti in json_missing_utis:
                    print(f"  {uti}")
            else:
                print("  (none)")
            print("Register fx extensions:")
            if json_missing_extensions:
                for extension in json_missing_extensions:
                    print(f"  .{extension}")
            else:
                print("  (none)")
            return

        applications = Path.home() / "Applications"
        app = applications / "nvim.app"
        terminate_running_handler(app)
        write_macos_app(
            app,
            name="Neovim",
            bundle_id=BUNDLE_ID,
            command=[str(ROOT / "bin/hx-hax")],
            role="Editor",
            utis=sorted({*explicit_utis, *source_utis, *claimed_extension_utis}),
            launcher_source=ROOT / "libexec/setup/file-handler.swift",
            declared_extensions=extensions,
            declared_parent="public.plain-text",
        )
        compile_launcher(app / "Contents/MacOS/file-handler")
        run([str(LSREGISTER), "-f", str(app)])
        fx_app = applications / "fx.app"
        terminate_running_handler(fx_app)
        write_macos_app(
            fx_app,
            name=json_handler["name"],
            bundle_id=json_bundle_id,
            command=["REAL_EDITOR=fx", str(ROOT / "bin/hx-hax")],
            role=json_handler["role"],
            utis=json_handler["utis"],
            launcher_source=ROOT / "libexec/setup/file-handler.swift",
        )
        compile_launcher(fx_app / "Contents/MacOS/file-handler")
        run([str(LSREGISTER), "-f", str(fx_app)])
        for uti in missing_utis:
            run(["duti", "-s", BUNDLE_ID, uti, "editor"])
        for extension in missing_extensions:
            run(
                [
                    "duti",
                    "-s",
                    BUNDLE_ID,
                    managed_extension_utis[extension],
                    "editor",
                ]
            )
            if extension not in ambiguous_extensions and extension in extension_utis:
                run(
                    [
                        "duti",
                        "-s",
                        BUNDLE_ID,
                        extension_utis[extension],
                        "editor",
                    ]
                )
            run(["duti", "-s", BUNDLE_ID, f".{extension}", "editor"])
        json_role = json_handler["role"].lower()
        for uti in json_missing_utis:
            run(["duti", "-s", json_bundle_id, uti, json_role])
        for extension in json_missing_extensions:
            run(["duti", "-s", json_bundle_id, f".{extension}", json_role])
        if preferences_available:
            if not export_launch_services(preferences_path):
                raise RuntimeError("could not re-read Launch Services associations")
            with preferences_path.open("rb") as input_file:
                preferences = plistlib.load(input_file)
            remove_macos_bundle_handlers(preferences, BUNDLE_ID, desired_utis)
            remove_macos_bundle_handlers(
                preferences, json_bundle_id, json_desired_utis
            )
            with clean_path.open("wb") as output:
                plistlib.dump(preferences, output, sort_keys=False)
            run(
                ["defaults", "import", LAUNCH_SERVICES_DOMAIN, str(clean_path)],
                stdout=subprocess.DEVNULL,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure default file handlers")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the associations that would change without changing them",
    )
    arguments = parser.parse_args()
    policy = load_policy(POLICY_PATH)
    try:
        platform = os.environ.get("SETUP_MIMETYPES_PLATFORM", sys.platform)
        if platform == "darwin":
            macos_setup(policy, arguments.dry_run)
        elif command_exists("xdg-mime"):
            linux_setup(policy, arguments.dry_run)
        else:
            raise RuntimeError("neither macOS Launch Services nor xdg-mime is available")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"setup-mimetypes: {error}\n")


if __name__ == "__main__":
    main()
