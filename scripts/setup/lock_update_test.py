#!/usr/bin/env python3

import importlib.machinery
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
LOADER = importlib.machinery.SourceFileLoader(
    "update_bootstrap_lock", str(ROOT / "scripts/update-bootstrap-lock")
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
updater = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(updater)


class LockUpdateTests(unittest.TestCase):
    def test_updates_git_heads_and_release_tags(self) -> None:
        manifest = {
            "git": {
                "head": {
                    "url": "https://github.com/example/head.git",
                    "revision": "old",
                    "update": {"type": "git-head"},
                },
                "release": {
                    "url": "https://github.com/example/release.git",
                    "revision": "old",
                    "update": {
                        "type": "github-release",
                        "repository": "example/release",
                    },
                },
            }
        }
        with mock.patch.object(
            updater, "git_revision", side_effect=("a" * 40, "b" * 40)
        ) as revision:
            updater.update_git_entries(
                manifest, lambda _url: {"tag_name": "v2.0.0"}
            )

        self.assertEqual("a" * 40, manifest["git"]["head"]["revision"])
        self.assertEqual("b" * 40, manifest["git"]["release"]["revision"])
        self.assertEqual("v2.0.0", manifest["git"]["release"]["version"])
        revision.assert_any_call("https://github.com/example/head.git")
        revision.assert_any_call(
            "https://github.com/example/release.git", "refs/tags/v2.0.0"
        )

    def test_updates_derived_raw_file_and_checksum(self) -> None:
        manifest = {
            "git": {
                "plugin": {
                    "url": "https://github.com/example/plugin.git",
                    "revision": "a" * 40,
                }
            },
            "downloads": {
                "installer": {
                    "url": "old",
                    "sha256": "old",
                    "update": {
                        "type": "github-file",
                        "revision_from": "plugin",
                        "path": "install.sh",
                    },
                }
            },
        }
        updater.update_download_entries(manifest, lambda _url: {}, lambda _url: b"new")

        entry = manifest["downloads"]["installer"]
        self.assertEqual(
            f"https://raw.githubusercontent.com/example/plugin/{'a' * 40}/install.sh",
            entry["url"],
        )
        self.assertEqual(updater.hashlib.sha256(b"new").hexdigest(), entry["sha256"])

    def test_release_file_url_keeps_the_human_readable_tag(self) -> None:
        manifest = {
            "git": {
                "plugin": {
                    "url": "https://github.com/example/plugin.git",
                    "revision": "a" * 40,
                    "version": "v2.0.0",
                }
            },
            "downloads": {
                "installer": {
                    "url": "old",
                    "sha256": "old",
                    "update": {
                        "type": "github-file",
                        "revision_from": "plugin",
                        "path": "install.sh",
                    },
                }
            },
        }

        updater.update_download_entries(manifest, lambda _url: {}, lambda _url: b"new")

        self.assertEqual(
            "https://raw.githubusercontent.com/example/plugin/v2.0.0/install.sh",
            manifest["downloads"]["installer"]["url"],
        )

    def test_bundle_uses_release_digest_without_downloading_asset(self) -> None:
        manifest = {
            "tool": {
                "platforms": {"linux-x86_64": "old"},
                "sha256": {"linux-x86_64": "old"},
                "update": {
                    "repository": "example/tool",
                    "assets": {"linux-x86_64": "tool.zip"},
                },
            }
        }
        get_bytes = mock.Mock(side_effect=AssertionError("unexpected download"))
        updater.update_bundles(
            manifest,
            lambda _url: {
                "assets": [
                    {
                        "name": "tool.zip",
                        "browser_download_url": "https://example.invalid/tool.zip",
                        "digest": f"sha256:{'c' * 64}",
                    }
                ]
            },
            get_bytes,
        )

        self.assertEqual(
            "https://example.invalid/tool.zip",
            manifest["tool"]["platforms"]["linux-x86_64"],
        )
        self.assertEqual("c" * 64, manifest["tool"]["sha256"]["linux-x86_64"])
        get_bytes.assert_not_called()

    def test_every_locked_input_has_update_metadata(self) -> None:
        bootstrap = updater.json.loads((ROOT / "install/bootstrap.lock.json").read_text())
        bundles = updater.json.loads((ROOT / "install/bundles.json").read_text())

        for entries in bootstrap.values():
            for entry in entries.values():
                self.assertIn("update", entry)
        for bundle in bundles.values():
            self.assertIn("update", bundle)

    def test_dry_run_prints_diff_without_writing_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            bootstrap = directory / "bootstrap.json"
            bundles = directory / "bundles.json"
            bootstrap.write_text('{"git": {}, "downloads": {}}\n')
            bundles.write_text("{}\n")
            before = (bootstrap.read_bytes(), bundles.read_bytes())

            def change_git(manifest: dict, _get_json: object) -> None:
                manifest["changed"] = True

            output = io.StringIO()
            with (
                mock.patch.object(updater, "update_git_entries", side_effect=change_git),
                mock.patch.object(updater, "update_download_entries"),
                mock.patch.object(updater, "update_bundles"),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "update-bootstrap-lock",
                        "--dry-run",
                        "--bootstrap-manifest",
                        str(bootstrap),
                        "--bundles-manifest",
                        str(bundles),
                    ],
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(0, updater.main())

            self.assertEqual(before, (bootstrap.read_bytes(), bundles.read_bytes()))
            self.assertIn('+  "changed": true,', output.getvalue())


if __name__ == "__main__":
    unittest.main()
