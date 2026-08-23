#!/usr/bin/env python3

import itertools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/agent-permissions"
RENDERER = TOOL / "render.clj"
FIXTURES = TOOL / "tests/fixtures"


class AgentPermissionRendererTests(unittest.TestCase):
    def render(
        self, target: str, policy: str, base: dict[str, object] | None = None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            policy_path = directory / "policy.clj"
            policy_path.write_text(policy)
            command = [
                "bb",
                "--config",
                "/dev/null",
                str(RENDERER),
                target,
                str(policy_path),
            ]
            if base is not None:
                base_path = directory / "base.json"
                base_path.write_text(json.dumps(base))
                command.append(str(base_path))
            return subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def render_paths(
        self, target: str, policy: Path, base: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "bb",
            "--config",
            "/dev/null",
            str(RENDERER),
            target,
            str(policy),
        ]
        if base is not None:
            command.append(str(base))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def render_fixture(self, target: str) -> subprocess.CompletedProcess[str]:
        command = [
            "bb",
            "--config",
            "/dev/null",
            str(RENDERER),
            target,
            str(FIXTURES / "sample-policy.clj"),
        ]
        if target == "claude":
            command.append(str(FIXTURES / "claude-base.json"))
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def codex_rule_calls(source: str) -> list[dict[str, object]]:
        calls: list[dict[str, object]] = []
        exec(source, {"prefix_rule": lambda **rule: calls.append(rule)})
        return calls

    def test_sample_policy_renders_expected_codex_rules(self) -> None:
        result = self.render_fixture("codex")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((FIXTURES / "codex.rules").read_text(), result.stdout)

    def test_sample_policy_renders_expected_claude_settings(self) -> None:
        result = self.render_fixture("claude")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            (FIXTURES / "claude-settings.json").read_text(),
            result.stdout,
        )

    def test_port_preserves_existing_codex_rule_decisions(self) -> None:
        result = self.render_paths("codex", TOOL / "current-policy.clj")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            self.codex_rule_calls((ROOT / "config/codex.rules").read_text()),
            self.codex_rule_calls(result.stdout),
        )

    def test_shared_policy_retains_claude_rules_and_adds_codex_allows(self) -> None:
        original = json.loads((ROOT / "config/claude.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            base = json.loads(json.dumps(original))
            for decision in ("allow", "deny"):
                base.setdefault("permissions", {})[decision] = [
                    entry
                    for entry in base.get("permissions", {}).get(decision, [])
                    if not entry.startswith("Bash(")
                ]
            base_path = Path(temporary) / "base.json"
            base_path.write_text(json.dumps(base))
            result = self.render_paths(
                "claude", TOOL / "current-policy.clj", base_path
            )

        self.assertEqual(0, result.returncode, result.stderr)
        generated = json.loads(result.stdout)
        self.assertFalse(
            any(
                entry.startswith("Bash(")
                for decision in ("allow", "deny")
                for entry in original.get("permissions", {}).get(decision, [])
            ),
            "base Claude settings must not duplicate generated Bash rules",
        )
        generated_bash = {
            decision: {
                entry
                for entry in generated.get("permissions", {}).get(decision, [])
                if entry.startswith("Bash(")
            }
            for decision in ("allow", "deny")
        }
        for decision in ("allow", "deny"):
            existing = {
                entry
                for entry in original.get("permissions", {}).get(decision, [])
                if entry.startswith("Bash(")
            }
            self.assertLessEqual(existing, generated_bash[decision], decision)

        for permission in {
            "Bash(clojure -Stree)",
            "Bash(clj-kondo *)",
            "Bash(git check-ignore *)",
            "Bash(find *)",
            "Bash(awk *)",
            "Bash(sed *)",
            "Bash(xxd)",
            "Bash(command -v *)",
            "Bash(python3 -m json.tool)",
            "Bash(typst *)",
        }:
            self.assertIn(permission, generated_bash["allow"])
        self.assertNotIn("Bash(xxd *)", generated_bash["allow"])
        self.assertNotIn("Bash(sed)", generated_bash["allow"])

        codex_rules = self.codex_rule_calls(
            (ROOT / "config/codex.rules").read_text()
        )
        for rule in codex_rules:
            if rule["decision"] != "allow":
                continue
            alternatives = [
                component if isinstance(component, list) else [component]
                for component in rule["pattern"]
            ]
            for tokens in itertools.product(*alternatives):
                command = " ".join(tokens)
                self.assertIn(f"Bash({command})", generated_bash["allow"])
                self.assertIn(f"Bash({command} *)", generated_bash["allow"])

    def test_rejects_unknown_rule_fields_instead_of_broadening_targets(self) -> None:
        result = self.render(
            "codex",
            '[{:decision :allow :match :prefix :pattern ["rm"] :reason nil '
            ':targets #{:codex :claude} :tragets #{:codex}}]\n',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("exactly the supported fields", result.stderr)

    def test_rejects_reasons_on_allow_rules(self) -> None:
        result = self.render(
            "codex",
            '[{:decision :allow :match :prefix :pattern ["echo"] '
            ':reason "mistaken" :targets #{:codex :claude}}]\n',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("allow rules cannot have reasons", result.stderr)

    def test_rejects_unmigrated_claude_bash_rules(self) -> None:
        result = self.render(
            "claude",
            '[{:decision :allow :match :prefix :pattern ["echo"] '
            ':reason nil :targets #{:codex :claude}}]\n',
            {"permissions": {"allow": ["Bash(handwritten-special *)"]}},
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("still contain Bash rules", result.stderr)

    def test_policy_can_define_and_use_ordinary_clojure_functions(self) -> None:
        result = self.render(
            "codex",
            """(defn allow-each [program commands]
  (mapv (fn [command]
          {:decision :allow
           :match :prefix
           :pattern [program command]
           :reason nil
           :targets #{:codex :claude}})
        commands))

(allow-each "jj" ["status" "diff"])
""",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('allow(["jj", "status"])', result.stdout)
        self.assertIn('allow(["jj", "diff"])', result.stdout)

    def test_planner_denies_untracked_effects(self) -> None:
        attempts = {
            "read": '(slurp "/etc/passwd")',
            "write": '(spit "/tmp/agent-permission-escape" "bad")',
            "namespace loading": "(require '[babashka.process :as process])",
            "host interop": '(System/getenv "HOME")',
        }
        for name, attempt in attempts.items():
            with self.subTest(name=name):
                result = self.render("codex", f"(do {attempt} [])\n")
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("root:", result.stdout + result.stderr)

    def test_rejects_tokens_that_cannot_be_rendered_equivalently(self) -> None:
        result = self.render(
            "codex",
            '[{:decision :allow :match :prefix :pattern ["echo bad"] '
            ':reason nil :targets #{:codex :claude}}]\n',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("patterns must be nonempty vectors", result.stderr)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is unavailable")
    def test_codex_accepts_and_evaluates_generated_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rules = Path(temporary) / "generated.rules"
            rules.write_text(self.render_fixture("codex").stdout)
            result = subprocess.run(
                [
                    "codex",
                    "execpolicy",
                    "check",
                    "--rules",
                    str(rules),
                    "jj",
                    "status",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("allow", json.loads(result.stdout)["decision"])


if __name__ == "__main__":
    unittest.main()
