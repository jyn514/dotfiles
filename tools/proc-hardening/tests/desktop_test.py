"""Exercise the real Unix transport, stdio handoff, and fixed app boundary."""
import array
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "desktop.py"
spec = importlib.util.spec_from_file_location("private_desktop", SOURCE)
desktop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = desktop
spec.loader.exec_module(desktop)


class RequestTests(unittest.TestCase):
    def request(self, **overrides):
        return {"argv": ["--new-window", "https://example.invalid/"],
                "cwd": "/tmp", "env": {"LANG": "C.UTF-8"}, **overrides}

    def test_rejects_injection_before_launch(self):
        invalid = [
            None, [], {**self.request(), "executable": "/bin/sh"},
            self.request(argv="--new-window"), self.request(argv=["bad\0value"]),
            self.request(cwd="relative"), self.request(env={"LD_PRELOAD": "inject.so"}),
            self.request(env={"PYTHONPATH": "/tmp"}), self.request(env={"HOME": "/tmp"}),
            self.request(env={"LC_ALL=invalid": "x"}), self.request(env={"PATH": 3}),
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                desktop.parse_request(request)

    def test_preserves_argument_boundaries_and_desktop_environment(self):
        request = self.request(argv=["", "a b", "--profile", "/a path", "a\nb", "☃"],
                               env={"LC_ALL": "C", "WAYLAND_DISPLAY": "wayland-99"})
        self.assertEqual(request, desktop.parse_request(request))

    def test_service_credentials_preserve_primary_gids_and_do_not_grant_root(self):
        application = desktop.Application("/bin/true", "fixture")
        account = pwd.struct_passwd(("desktop", "x", 4321, 8765, "", "/home/desktop", "/bin/fish"))
        with patch.object(desktop.os, "getresuid", return_value=(4321,) * 3), \
             patch.object(desktop.os, "getresgid", return_value=(8765,) * 3), \
             patch.object(desktop.os, "getgroups", return_value=[8765, 2222]), \
             patch.object(desktop.grp, "getgrnam", return_value=grp.struct_group(("fixture", "x", 2222, []))):
            desktop.check_identity(application, account)
            with patch.object(desktop.os, "getresgid", return_value=(2222,) * 3), self.assertRaises(ValueError):
                desktop.check_identity(application, account)
            with patch.object(desktop.os, "getgroups", return_value=[8765]), self.assertRaises(ValueError):
                desktop.check_identity(application, account)
            root = pwd.struct_passwd(("root", "x", 0, 0, "", "/root", "/bin/sh"))
            with self.assertRaises(ValueError):
                desktop.check_identity(application, root)

    def test_onepassword_accepts_desktop_launches_but_rejects_executable_switches(self):
        app = desktop.APPLICATIONS["onepassword"]
        values = ["--silent", "onepassword://open?vault=a", "onepassword8://open?a=b"]
        self.assertEqual(["--ozone-platform=wayland", *values], desktop.application_arguments(app, values, {"WAYLAND_DISPLAY": "fixture"}))
        for argv in (["--gpu-launcher=/bin/sh"], ["--renderer-cmd-prefix", "/bin/sh"], ["--user-data-dir=/tmp"], ["--inspect"], ["https://example.invalid"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                desktop.application_arguments(app, argv, {})

    def test_profiles_include_install_defaults_and_resolve_escaping_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            registry.mkdir()
            (registry / "local").mkdir()
            (root / "external").mkdir()
            (registry / "link").symlink_to(root / "external")
            (registry / "profiles.ini").write_text(
                f"[Profile0]\nPath=local\nIsRelative=1\n[Profile1]\nPath={root / 'external'}\nIsRelative=0\n"
                "[Installfixture]\nDefault=link\n"
            )
            self.assertEqual({registry / "local", root / "external"}, desktop.registered_profiles(registry))
            with self.assertRaisesRegex(ValueError, "outside protected storage"):
                desktop.check_registered_profiles(registry, registry)
            (root / "installation-default").mkdir()
            (registry / "installs.ini").write_text("[separate-hash]\nDefault=../installation-default\n")
            self.assertEqual({registry / "local", root / "external", root / "installation-default"}, desktop.registered_profiles(registry))
            (registry / "profiles.ini").write_text("[Profile0]\nPath=local\nIsRelative=1\n")
            (registry / "installs.ini").unlink()
            desktop.check_registered_profiles(registry, registry)
            (registry / "profiles.ini").write_text("[Profile0]\nPath=/absolute\nIsRelative=1\n")
            with self.assertRaises(ValueError):
                desktop.registered_profiles(registry)

    def test_read_frame_handles_fragmented_utf8_and_headers(self):
        class Fragments:
            def __init__(self, fragments):
                self.fragments = fragments
            def recv(self, limit):
                head, *self.fragments = self.fragments
                if len(head) > limit:
                    self.fragments.insert(0, head[limit:])
                return head[:limit]
        value = {"argv": ["☃", "newline\\n", "--", "a b"]}
        data = json.dumps(value, ensure_ascii=False).encode()
        packet = struct.pack("!I", len(data)) + data
        self.assertEqual(value, desktop.receive_frame(Fragments([bytes([byte]) for byte in packet])))

    def test_path_wrapper_is_native_before_install_and_never_falls_back_after_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "installed"
            with patch.object(desktop, "INSTALLED", installed), \
                 patch.object(sys, "argv", ["glide-bin", "--new-window", "https://example.invalid"]), \
                 patch.object(desktop.os, "execv", side_effect=SystemExit(0)) as native:
                with self.assertRaises(SystemExit):
                    desktop.main()
                native.assert_called_once_with(desktop.APPLICATIONS["glide"].executable,
                    [desktop.APPLICATIONS["glide"].executable, "--new-window", "https://example.invalid"])
                native.reset_mock()
                installed.touch()
                with self.assertRaises(SystemExit):
                    desktop.main()
                native.assert_called_once_with("/usr/bin/python3", ["/usr/bin/python3", "-I", str(installed),
                    "launch", "glide", "--", "--new-window", "https://example.invalid"])

    def test_rendered_service_follows_application_authority(self):
        application = desktop.Application("/synthetic/browser", "synthetic-group")
        with patch.dict(desktop.APPLICATIONS, {"glide": application}):
            units = desktop.render_units(4321, 8765)
        service = units["private-desktop-4321-glide@.service"]
        self.assertIn("User=4321\nGroup=8765\nSupplementaryGroups=synthetic-group\n", service)
        self.assertIn("serve glide\n", service)
        self.assertIn("Requires=proc-read-guard@4321.service", service)
        self.assertIn("StandardInput=socket", service)
        self.assertNotIn("NoNewPrivileges=", service)  # Native connector needs its setgid transition.
        self.assertIn("SocketUser=4321\nSocketMode=0600", units["private-desktop-4321-glide.socket"])
        with self.assertRaises(ValueError):
            desktop.render_units(0, 8765)


@unittest.skipIf(os.getuid() == 0, "transport fixture requires a non-root desktop uid")
class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-launch-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "launch.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        self.listener.listen()
        self.listener.settimeout(10)
        self.addCleanup(self.listener.close)
        self.account = pwd.getpwuid(os.getuid())
        group = grp.getgrgid(os.getgroups()[0]).gr_name
        self.application = desktop.Application(sys.executable, group, (str(HERE / "desktop_app_fixture.py"),))
        self.results = []
        self.failures = []

    def start_worker(self, application=None):
        def worker():
            try:
                connection, _ = self.listener.accept()
                with connection:
                    self.results.append(desktop.serve(connection, application or self.application, self.account))
            except BaseException as error:
                self.failures.append(error)
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
        self.addCleanup(self.join_worker)

    def join_worker(self):
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive(), "worker did not finish")
        self.assertEqual([], self.failures)

    def client(self, *argv):
        # Explicitly remove ambient selectors; no real profile, bus or socket is used.
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.root), "LANG": "C.UTF-8",
               "WAYLAND_DISPLAY": "fixture-wayland", "LC_NUMERIC": "C",
               "PYTHONPATH": "/untrusted", "LD_LIBRARY_PATH": "/untrusted"}
        return subprocess.run(
            [sys.executable, str(HERE / "desktop_client_fixture.py"), str(SOURCE), str(self.path), *argv],
            input="test input\n", text=True, capture_output=True, env=env, cwd=self.root, timeout=15,
        )

    def test_cli_roundtrip_preserves_arguments_stdio_and_environment_without_socket_leaks(self):
        self.start_worker()
        argv = ["--new-window", "https://example.invalid/a?x=1&y=2", "", "space quote'\"", "☃", "a\nb", "--read-stdin"]
        result = self.client(*argv)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(argv, report["argv"])
        self.assertEqual("test input\n", report["input"])
        self.assertEqual(str(self.root), report["cwd"])
        self.assertEqual(self.account.pw_dir, report["env"]["HOME"])
        self.assertEqual("fixture-wayland", report["env"]["WAYLAND_DISPLAY"])
        self.assertEqual("C", report["env"]["LC_NUMERIC"])
        self.assertNotIn("PYTHONPATH", report["env"])
        self.assertNotIn("LD_LIBRARY_PATH", report["env"])
        self.assertEqual([], report["sockets"])
        self.assertIn("fixture diagnostic", result.stderr)
        self.join_worker()
        self.assertEqual([0], self.results)

    def test_cli_reports_app_exit_and_signal(self):
        for argument, expected in (("--failure", 7), ("--signal", 143)):
            with self.subTest(argument=argument):
                self.start_worker()
                result = self.client(argument)
                self.assertEqual(expected, result.returncode, result.stderr)
                self.join_worker()

    def test_exec_failure_reaches_cli(self):
        self.start_worker(desktop.Application("/nonexistent-private-app", self.application.group))
        result = self.client()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("No such file", result.stderr)
        self.assertEqual("", result.stdout)

    def send_request(self, request, split=False, trailing=b"", descriptors=None):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(connection.close)
        connection.connect(str(self.path))
        descriptors = array.array("i", descriptors or [0, 1, 2])
        connection.sendmsg([b"S"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors)])
        data = json.dumps(request).encode()
        packet = struct.pack("!I", len(data)) + data + trailing
        if split:
            for byte in packet:
                connection.sendall(bytes([byte]))
        else:
            connection.sendall(packet)
        connection.shutdown(socket.SHUT_WR)
        return connection

    def test_partial_stream_reads_and_disconnection_do_not_kill_app(self):
        self.start_worker()
        done = self.root / "done"
        with (self.root / "output").open("w+") as output:
            request = {"argv": ["--wait-file", str(done)], "cwd": str(self.root), "env": {}}
            connection = self.send_request(request, split=True, descriptors=[output.fileno()] * 3)
            try:
                response = desktop.receive_frame(connection)
                self.assertIn("started", response)
                connection.close()
                # Worker still owns the running app after client departure.
                self.assertTrue(self.thread.is_alive())
            finally:
                done.touch()
                self.join_worker()
        self.assertEqual([0], self.results)

    def test_trailing_data_rejected_before_spawn(self):
        self.start_worker()
        request = {"argv": [], "cwd": str(self.root), "env": {}}
        with patch.object(desktop.subprocess, "Popen") as spawn:
            connection = self.send_request(request, trailing=b"not another request")
            self.assertIn("unexpected data", desktop.receive_frame(connection)["error"])
            self.join_worker()
            spawn.assert_not_called()

    def test_rejects_truncated_and_oversized_frames(self):
        for packet in (struct.pack("!I", 50) + b"{}", struct.pack("!I", desktop.MAX_FRAME + 1)):
            self.start_worker()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self.path))
                connection.sendmsg([b"S"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [0, 1, 2]))])
                connection.sendall(packet)
                connection.shutdown(socket.SHUT_WR)
                self.assertIn("error", desktop.receive_frame(connection))
            self.join_worker()


if __name__ == "__main__":
    unittest.main()
