#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "libexec/agent-wrappers/jj"


class JjWrapperTest(unittest.TestCase):
    def test_forwards_pi_model_identity_to_sandbox_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_file = root / "identity"
            client = root / "client"
            client.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n%s\\n" "$JJ_USER" "$JJ_EMAIL" > "$RESULT_FILE"\n'
            )
            client.chmod(0o755)
            wrapper = root / "jj"
            wrapper.write_text(
                WRAPPER.read_text().replace(
                    "/libexec/agent-wrappers/jj-proxy-client", str(client)
                )
            )
            wrapper.chmod(0o755)

            result = subprocess.run(
                [str(wrapper), "status"],
                env={
                    **os.environ,
                    "JJ_AGENT": "pi",
                    "PI_MODEL": "gpt-test-model",
                    "RESULT_FILE": str(result_file),
                    "SANDBOX_PROXY_DIR": str(root / "proxy"),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["Pi gpt-test-model", "breq@jyn.dev"],
                result_file.read_text().splitlines(),
            )

    def test_auto_detects_pi_without_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_file = root / "identity"
            client = root / "client"
            client.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n%s\\n" "$JJ_USER" "$JJ_EMAIL" > "$RESULT_FILE"\n'
            )
            client.chmod(0o755)
            wrapper = root / "jj"
            wrapper.write_text(
                WRAPPER.read_text().replace(
                    "/libexec/agent-wrappers/jj-proxy-client", str(client)
                )
            )
            wrapper.chmod(0o755)
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"JJ_AGENT", "PI_MODEL"}
            }
            env.update(
                {
                    "PI_CODING_AGENT": "true",
                    "RESULT_FILE": str(result_file),
                    "SANDBOX_PROXY_DIR": str(root / "proxy"),
                }
            )

            result = subprocess.run(
                [str(wrapper), "status"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["Pi", "breq@jyn.dev"],
                result_file.read_text().splitlines(),
            )

    def test_forwards_codex_model_identity_to_sandbox_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / "codex"
            session = codex_home / "sessions/2026/08/01/rollout-thread-123.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text(
                '{"type":"turn_context","payload":{"model":"gpt-test-model"}}\n'
            )
            result_file = root / "identity"
            client = root / "client"
            client.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n%s\\n" "$JJ_USER" "$JJ_EMAIL" > "$RESULT_FILE"\n'
            )
            client.chmod(0o755)
            wrapper = root / "jj"
            wrapper.write_text(
                WRAPPER.read_text().replace(
                    "/libexec/agent-wrappers/jj-proxy-client", str(client)
                )
            )
            wrapper.chmod(0o755)

            result = subprocess.run(
                [str(wrapper), "status"],
                env={
                    **os.environ,
                    "JJ_AGENT": "codex",
                    "CODEX_HOME": str(codex_home),
                    "CODEX_THREAD_ID": "thread-123",
                    "RESULT_FILE": str(result_file),
                    "SANDBOX_PROXY_DIR": str(root / "proxy"),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["Codex gpt-test-model", "breq@jyn.dev"],
                result_file.read_text().splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
