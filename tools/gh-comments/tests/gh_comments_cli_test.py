import http.server
import json
import os
from pathlib import Path
import signal
import socketserver
import shutil
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_native_gh_capture_disables_internal_pager_but_keeps_final_less(self) -> None:
        gh = shutil.which("gh")
        less = shutil.which("less")
        if gh is None or less is None:
            self.skipTest("native gh and less are required")
        # This is a native gh integration, not the printing-shell gh used below.
        version = subprocess.run([gh, "--version"], capture_output=True, text=True)
        if version.returncode or not version.stdout.startswith("gh version "):
            self.skipTest("gh on PATH is not the native GitHub CLI")
        comments = {
            "nodes": [{
                "author": {"login": "fixture-commenter"},
                "authorAssociation": "NONE",
                "body": "\n".join(f"Native comment line {i}" for i in range(100)),
                "createdAt": "2026-01-01T00:00:00Z",
            }],
            "totalCount": 1,
            "pageInfo": {"hasNextPage": False, "endCursor": ""},
        }
        issue = {
            "id": "fixture-issue", "number": 123, "title": "Offline fixture title",
            "body": "Offline fixture body", "state": "OPEN",
            "createdAt": "2026-01-01T00:00:00Z",
            "author": {"login": "fixture-author"}, "comments": comments,
            "url": "https://github.com/fixture/owned/issues/123",
        }

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if "IssueByNumber" in body["query"]:
                    data = {"repository": {"hasIssuesEnabled": True, "issue": issue}}
                elif "CommentsForIssue" in body["query"]:
                    data = {"node": {"comments": comments}}
                else:
                    self.send_error(400)
                    return
                encoded = json.dumps({"data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_):
                pass

        socket = self.directory / "http.sock"
        server = socketserver.UnixStreamServer(str(socket), Handler)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        config = self.directory / "gh-config"
        config.mkdir()
        environment = os.environ.copy()
        for key in (
            "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
            "GH_CONFIG_DIR", "GH_HOST", "GH_REPO", "GH_PAGER", "PAGER", "GH_FORCE_TTY",
            "CLICOLOR_FORCE", "FORCE_COLOR", "LESS", "LESSOPEN", "LESSCLOSE", "LESSHISTFILE",
        ):
            environment.pop(key, None)
        environment.update({
            "GH_CONFIG_DIR": str(config), "GH_TOKEN": "owned-disposable-not-a-credential",
            "TERM": "dumb", "NO_COLOR": "1", "GH_SPINNER_DISABLED": "1",
            "GH_PROMPT_DISABLED": "1",
        })
        for selector in ("GH_PAGER", "PAGER", "config"):
            with self.subTest(selector=selector):
                output = self.directory / selector
                output.mkdir()
                (config / "config.yml").write_text(
                    f"http_unix_socket: {socket}\n" +
                    (f"pager: {less}\n" if selector == "config" else "")
                )
                child = subprocess.Popen(
                    [str(ROOT / "bin/gh-comments"), issue["url"]], cwd=output,
                    env=environment | ({selector: less} if selector != "config" else {}),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                )
                try:
                    stdout, stderr = child.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()
                    self.fail("native gh internal pager waited for input during capture")
                self.assertEqual(0, child.returncode, stderr)
                text = (output / "123.txt").read_bytes()
                for expected in (
                    b"Offline fixture title", b"Offline fixture body", b"Native comment line 99",
                    b"View this issue on GitHub: https://github.com/fixture/owned/issues/123",
                ):
                    self.assertIn(expected, text)
                self.assertIn(text, stdout)  # The final real less displays the complete artifact.
                self.assertIn(b"saved 123.txt and 123.json", stdout)
                exported = json.loads((output / "123.json").read_bytes())
                self.assertEqual(comments["nodes"][0]["body"], exported["comments"][0]["body"])

    def test_gh_comments_normalizes_url_and_rejects_unsafe_issue_names(self) -> None:
        calls = self.directory / "gh-calls"
        self.executable(
            "gh",
            'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
            'case " $* " in *" --json "*) printf \'{}\\n\';; '
            "*) printf 'issue output\\n';; esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {
            "GH_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "github.com/user/repo/issues/123"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        unsafe = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "../escape"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("https://github.com/user/repo/issues/123", calls.read_text())
        self.assertEqual(2, len(calls.read_text().splitlines()))
        self.assertEqual(1, unsafe.returncode)
        self.assertFalse((self.directory.parent / "escape.json").exists())
    def test_gh_comments_does_not_publish_partial_exports(self) -> None:
        self.executable(
            "gh",
            'case " $* " in\n'
            '  *" --json "*) printf "json\\n"; '
            '[ -z "${GH_STATUS:-}" ] || exit "$GH_STATUS";;\n'
            '  *) printf "text\\n"; '
            '[ -z "${TEXT_STATUS:-}" ] || exit "$TEXT_STATUS";;\n'
            "esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"}

        for variable, status in (("GH_STATUS", 24), ("TEXT_STATUS", 25)):
            result = subprocess.run(
                [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
                cwd=self.directory,
                env=environment | {variable: str(status)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(status, result.returncode, variable)
            self.assertFalse((self.directory / "123.json").exists())
            self.assertFalse((self.directory / "123.txt").exists())
            self.assertEqual([], list(self.directory.glob(".123.*")))

        less_failure = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
            cwd=self.directory,
            env=environment | {"LESS_STATUS": "26"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(26, less_failure.returncode)
        self.assertEqual("json\n", (self.directory / "123.json").read_text())
        self.assertEqual("text\n", (self.directory / "123.txt").read_text())


if __name__ == "__main__":
    unittest.main()
