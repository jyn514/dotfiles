from contextlib import contextmanager
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/package-inspection"))
from package_inspection import what_package


@contextmanager
def filesystem_root(root: Path):
    # Project only the adapter's filesystem checks into a disposable root.
    # Native dpkg separately uses its supported DPKG_ROOT/DPKG_ADMINDIR options.
    resolve = Path.resolve
    is_symlink = Path.is_symlink

    def rooted_resolve(path: Path, strict: bool = False) -> Path:
        resolved = resolve(root / str(path).lstrip("/"), strict=strict)
        return Path("/") / resolved.relative_to(root)

    def rooted_is_symlink(path: Path) -> bool:
        return is_symlink(root / str(path).lstrip("/"))

    with mock.patch.object(Path, "resolve", autospec=True, side_effect=rooted_resolve):
        with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=rooted_is_symlink):
            yield


class DirectoryAliasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "usr/bin/tool").write_bytes(b"target")
        self.enterContext(filesystem_root(self.root))

    def test_directory_link_is_an_alias(self) -> None:
        (self.root / "bin").symlink_to("usr/bin", target_is_directory=True)
        self.assertEqual(Path("/bin/tool"), what_package.directory_alias("/usr/bin/tool"))

    def test_final_symlink_is_not_a_directory_alias(self) -> None:
        (self.root / "bin").mkdir()
        (self.root / "bin/tool").symlink_to("../usr/bin/tool")
        self.assertIsNone(what_package.directory_alias("/usr/bin/tool"))

    def test_final_symlink_inside_directory_alias_is_rejected(self) -> None:
        (self.root / "bin").symlink_to("usr/bin", target_is_directory=True)
        (self.root / "usr/bin/tool").unlink()
        (self.root / "usr/bin/other").write_bytes(b"other")
        (self.root / "usr/bin/tool").symlink_to("other")
        self.assertIsNone(what_package.directory_alias("/usr/bin/tool"))

    def test_regular_file_in_unrelated_directory_is_not_an_alias(self) -> None:
        (self.root / "bin").mkdir()
        (self.root / "bin/tool").write_bytes(b"different executable")
        self.assertIsNone(what_package.directory_alias("/usr/bin/tool"))

    def test_directory_alias_loop_is_rejected(self) -> None:
        (self.root / "bin").symlink_to("bin", target_is_directory=True)
        self.assertIsNone(what_package.directory_alias("/usr/bin/tool"))

    def test_missing_parent_and_paths_outside_usr_are_rejected(self) -> None:
        self.assertIsNone(what_package.directory_alias("/usr/bin/tool"))
        self.assertIsNone(what_package.directory_alias("/opt/bin/tool"))


class DpkgFallbackTest(unittest.TestCase):
    command = ["/native/dpkg", "-S", "--", "/usr/bin/tool"]

    def result(self, status: int, stdout: bytes = b"", stderr: bytes = b"") -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(self.command, status, stdout, stderr)

    def query(self, results: list, extras: tuple[str, ...] | list[str] = ()):
        with mock.patch.object(what_package, "directory_alias", return_value=Path("/bin/tool")):
            with mock.patch.object(what_package.subprocess, "run", side_effect=results) as run:
                result = what_package.query_dpkg([*self.command, *extras])
        return result, run

    def test_canonical_success_fatal_error_and_signal_do_not_retry(self) -> None:
        for status in (0, 2, -15):
            with self.subTest(status=status):
                original = self.result(status, b"partial\xff\x00", b"diagnostic\xfe")
                result, run = self.query([original])
                self.assertIs(original, result)
                self.assertEqual(1, run.call_count)

    def test_successful_alias_replaces_original_diagnostic(self) -> None:
        original = self.result(1, b"", b"missing canonical\xff")
        recovered = self.result(0, b"owner: /bin/tool\xfe\n")
        result, run = self.query([original, recovered])
        self.assertIs(recovered, result)
        self.assertEqual(["/native/dpkg", "-S", "--", "/bin/tool"], run.call_args.args[0])

    def test_unsuccessful_or_unavailable_retry_preserves_complete_original(self) -> None:
        for retry in (self.result(1), self.result(2), self.result(-15), FileNotFoundError("gone")):
            with self.subTest(retry=retry):
                original = self.result(1, b"original partial\xff", b"original error\xfe")
                result, _ = self.query([original, retry])
                self.assertIs(original, result)

    def test_additional_operand_failure_does_not_trigger_alias_for_owned_target(self) -> None:
        for canonical in (self.result(0, b"owner"), self.result(2), self.result(-15), OSError("gone")):
            with self.subTest(canonical=canonical):
                original = self.result(1, b"canonical owner\xff", b"missing extra\xfe")
                result, run = self.query([original, canonical], ["extra"])
                self.assertIs(original, result)
                self.assertEqual(2, run.call_count)
                self.assertEqual(self.command, run.call_args.args[0])

    def test_absent_target_retry_preserves_additional_operands(self) -> None:
        extras = ["path with spaces", "-opaque"]
        recovered = self.result(0, b"alias owner and extra owners")
        result, run = self.query([self.result(1), self.result(1), recovered], extras)
        self.assertIs(recovered, result)
        self.assertEqual(["/native/dpkg", "-S", "--", "/bin/tool", *extras], run.call_args.args[0])

    def test_partial_alias_retry_keeps_original_output(self) -> None:
        original = self.result(1, b"extra owner", b"canonical and other extra missing")
        result, _ = self.query([original, self.result(1), self.result(1, b"alias owner", b"extra missing")], ["extra"])
        self.assertIs(original, result)

    def test_no_verified_alias_means_no_retry(self) -> None:
        original = self.result(1)
        with mock.patch.object(what_package, "directory_alias", return_value=None):
            with mock.patch.object(what_package.subprocess, "run", return_value=original) as run:
                self.assertIs(original, what_package.query_dpkg(self.command))
        self.assertEqual(1, run.call_count)

    def test_initial_missing_manager_executable_keeps_error_status(self) -> None:
        errors = io.StringIO()
        with mock.patch.object(what_package, "ownership_command", return_value=self.command):
            with mock.patch.object(what_package.subprocess, "run", side_effect=FileNotFoundError("gone")):
                with mock.patch.object(sys, "stderr", errors):
                    self.assertEqual(127, what_package.main(["tool"]))
        self.assertIn("could not run package manager: gone", errors.getvalue())

    def test_main_publishes_bytes_and_maps_signal_status(self) -> None:
        output = io.TextIOWrapper(io.BytesIO())
        errors = io.TextIOWrapper(io.BytesIO())
        result = self.result(-15, b"output\xff\x00", b"errors\xfe\x00")
        with mock.patch.object(what_package, "ownership_command", return_value=self.command):
            with mock.patch.object(what_package, "query_dpkg", return_value=result):
                with mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", errors):
                    self.assertEqual(143, what_package.main(["tool"]))
        self.assertEqual(result.stdout, output.buffer.getvalue())
        self.assertEqual(result.stderr, errors.buffer.getvalue())


@unittest.skipUnless(shutil.which("dpkg") and shutil.which("dpkg-deb"), "native dpkg and dpkg-deb are unavailable")
class NativeDpkgFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / "root"
        self.root.mkdir()
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "bin").symlink_to("usr/bin", target_is_directory=True)
        self.dpkg = shutil.which("dpkg")
        self.environment = mock.patch.dict(os.environ, {"DPKG_ROOT": str(self.root), "DPKG_ADMINDIR": str(self.root / "var/lib/dpkg"), "LC_ALL": "C"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def install(self, name: str, path: str, symlink: str | None = None) -> None:
        package = self.directory / name
        control = package / "DEBIAN/control"
        control.parent.mkdir(parents=True)
        control.write_text(f"Package: {name}\nVersion: 1\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: disposable ownership fixture\n")
        payload = package / path.lstrip("/")
        payload.parent.mkdir(parents=True)
        if symlink is None:
            payload.write_bytes(b"disposable executable payload\n")
            payload.chmod(0o755)
        else:
            payload.symlink_to(symlink)
        archive = self.directory / f"{name}.deb"
        subprocess.run([shutil.which("dpkg-deb"), "--build", str(package), str(archive)], check=True, capture_output=True)
        # Native unpack generates the ownership database. No maintainer scripts,
        # network, real package database, root privilege, or edited .list files.
        subprocess.run([self.dpkg, "--root=" + str(self.root), "--force-not-root", "--force-bad-path", "--unpack", str(archive)], check=True, capture_output=True)

    def command(self, *paths: str) -> list[str]:
        return [self.dpkg, "-S", "--", *paths]

    def native(self, *paths: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(self.command(*paths), check=False, capture_output=True)

    def query(self, *paths: str) -> subprocess.CompletedProcess[bytes]:
        with filesystem_root(self.root):
            return what_package.query_dpkg(self.command(*paths))

    def test_native_alias_recovery_and_missing_additional_operand(self) -> None:
        self.install("target-owner", "/bin/tool")
        self.assertEqual(0, self.native("/bin/tool").returncode)
        self.assertEqual(1, self.native("/usr/bin/tool").returncode)
        recovered = self.query("/usr/bin/tool")
        self.assertEqual((0, b"target-owner: /bin/tool\n", b""), (recovered.returncode, recovered.stdout, recovered.stderr))
        original = self.native("/usr/bin/tool", "/missing-extra")
        failed = self.query("/usr/bin/tool", "/missing-extra")
        self.assertEqual((original.returncode, original.stdout, original.stderr), (failed.returncode, failed.stdout, failed.stderr))

    def test_native_canonical_owner_and_partial_extra_are_preserved(self) -> None:
        self.install("canonical-owner", "/usr/bin/tool")
        original = self.native("/usr/bin/tool", "/missing-extra")
        result = self.query("/usr/bin/tool", "/missing-extra")
        self.assertEqual(1, original.returncode)
        self.assertIn(b"canonical-owner: /usr/bin/tool", original.stdout)
        self.assertEqual((original.returncode, original.stdout, original.stderr), (result.returncode, result.stdout, result.stderr))
        success = self.query("/usr/bin/tool")
        self.assertEqual((0, b"canonical-owner: /usr/bin/tool\n", b""), (success.returncode, success.stdout, success.stderr))

    def test_native_final_symlink_owner_is_not_the_target_owner(self) -> None:
        (self.root / "bin").unlink()
        (self.root / "bin").mkdir()
        self.install("symlink-owner", "/bin/tool", symlink="../usr/bin/tool")
        (self.root / "usr/bin/tool").write_bytes(b"unowned target")
        self.assertEqual(b"symlink-owner: /bin/tool\n", self.native("/bin/tool").stdout)
        original = self.native("/usr/bin/tool")
        result = self.query("/usr/bin/tool")
        self.assertEqual(1, result.returncode)
        self.assertEqual((original.stdout, original.stderr), (result.stdout, result.stderr))

    def test_native_unrelated_regular_file_owner_is_not_substituted(self) -> None:
        (self.root / "bin").unlink()
        (self.root / "bin").mkdir()
        self.install("other-owner", "/bin/tool")
        (self.root / "usr/bin/tool").write_bytes(b"different unowned target")
        self.assertEqual(b"other-owner: /bin/tool\n", self.native("/bin/tool").stdout)
        original = self.native("/usr/bin/tool")
        result = self.query("/usr/bin/tool")
        self.assertEqual(1, result.returncode)
        self.assertEqual((original.stdout, original.stderr), (result.stdout, result.stderr))

    def test_native_fatal_database_error_is_not_absence(self) -> None:
        self.install("canonical-owner", "/usr/bin/tool")
        (self.root / "var/lib/dpkg/status").write_bytes(b"malformed database\n")
        original = self.native("/usr/bin/tool")
        self.assertEqual(2, original.returncode)
        with mock.patch.object(what_package, "directory_alias") as alias:
            result = what_package.query_dpkg(self.command("/usr/bin/tool"))
        alias.assert_not_called()
        self.assertEqual((2, original.stdout, original.stderr), (result.returncode, result.stdout, result.stderr))


if __name__ == "__main__":
    unittest.main()
