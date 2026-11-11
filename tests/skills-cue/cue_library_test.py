"""Exercise imported skill contracts through the native CUE data validator."""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "skills/references/cue"
SOURCE = {"kind": "inline", "text": "Synthetic governing instruction for this test."}


class CueLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("DOTFILES_TEST_CUE_REAL")
        binary = shutil.which(configured or "cue")
        if not binary:
            if configured:
                raise RuntimeError(f"DOTFILES_TEST_CUE_REAL is not executable: {configured}")
            raise unittest.SkipTest("CUE is not installed; set DOTFILES_TEST_CUE_REAL to its executable")
        cls.cue = str(Path(binary).resolve())
        cls.temporary = tempfile.TemporaryDirectory(prefix="skill cue ")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "library"
        shutil.copytree(LIBRARY, cls.root)
        # Establish healthy source and real package imports before any negative
        # data cases; broken setup must not masquerade as correct rejection.
        for arguments in (("vet", "-c=false", "."), ("vet", "-c", "./examples")):
            result = cls.run_cue(*arguments)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def run_cue(cls, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [cls.cue, *arguments], cwd=cls.root, text=True,
            capture_output=True, timeout=20, check=False,
        )

    def assert_accepts(self, definition: str, value: object, expected: bool, package: str = ".") -> None:
        data = self.root / "case.json"
        data.write_text(json.dumps(value), encoding="utf-8")
        result = self.run_cue("vet", "-c", "-d", definition, package, str(data))
        self.assertEqual(
            result.returncode == 0, expected,
            f"{definition}: {json.dumps(value)}\n{result.stdout}{result.stderr}",
        )

    def test_imported_example_and_hidden_checks_do_not_leak_into_json(self) -> None:
        result = self.run_cue("export", "./examples", "-e", "review")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(set(record), {"task", "packet", "staffing"})
        self.assertEqual(record["staffing"]["constructors"], ["builder-a", "builder-b"])

    def test_connected_plan_preserves_conditional_independence_and_packet_identity(self) -> None:
        result = self.run_cue("export", "./examples", "-e", "review")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        effect = {"actor": "selected-owner", "action": "inspect", "target": "selected-target"}
        plan["task"]["grants"] = [{"effect": effect, "source": SOURCE}]
        plan["packet"] = {"owner": "selected-owner", "effects": [effect]}
        plan["staffing"] = {"constructors": ["selected-owner"], "verifiers": ["selected-owner"]}
        for required in (False, True):
            plan["task"]["independentVerificationRequired"] = required
            with self.subTest(independence_required=required):
                self.assert_accepts("#ReviewPlan", plan, not required, package="./examples")
        # A valid grant to someone else cannot authorize this packet's owner.
        plan["task"]["independentVerificationRequired"] = False
        other = {**effect, "actor": "another-owner"}
        plan["task"]["grants"] = [{"effect": other, "source": SOURCE}]
        plan["packet"]["effects"] = [other]
        with self.subTest(packet_owner_mismatch=True):
            self.assert_accepts("#ReviewPlan", plan, False, package="./examples")

    def test_membership_relations_match_small_set_oracles(self) -> None:
        # Exhaust all 16 pairs over a two-identity universe. Expectations use
        # Python sets, independently of the CUE membership comprehensions.
        universe = ("owner-a", "owner-b")
        subsets = [list(s) for size in range(3) for s in itertools.combinations(universe, size)]
        exercised = {"subset-yes": 0, "subset-no": 0, "disjoint-yes": 0, "disjoint-no": 0}
        for left, right in itertools.product(subsets, repeat=2):
            subset = set(right) <= set(left)
            disjoint = set(left).isdisjoint(right)
            with self.subTest(left=left, right=right, relation="subset"):
                self.assert_accepts("#Subset", {"superset": left, "subset": right}, subset)
            with self.subTest(left=left, right=right, relation="disjoint"):
                self.assert_accepts("#Disjoint", {"left": left, "right": right}, disjoint)
            exercised["subset-yes" if subset else "subset-no"] += 1
            exercised["disjoint-yes" if disjoint else "disjoint-no"] += 1
        self.assertTrue(all(exercised.values()), exercised)

    def test_relations_use_values_not_order_or_occurrence_counts(self) -> None:
        cases = [
            ("#Subset", {"superset": ["b", "a"], "subset": ["a", "a"]}, True),
            ("#Disjoint", {"left": ["a", "a"], "right": ["b", "b"]}, True),
            ("#Disjoint", {"left": ["a", "a"], "right": ["a"]}, False),
            ("#Subset", {"superset": [{"a": 1, "b": 2}], "subset": [{"b": 2, "a": 1}]}, True),
            ("#Subset", {"superset": [{"a": 1, "b": 2}], "subset": [{"a": 1}]}, False),
            ("#Disjoint", {"left": [["a", "b"]], "right": [["a", "b"]]}, False),
            ("#Disjoint", {"left": [False], "right": [0]}, True),
            ("#Subset", {"superset": ['quote" newline\n'], "subset": ['quote" newline\n']}, True),
        ]
        for definition, value, expected in cases:
            with self.subTest(definition=definition, value=value):
                self.assert_accepts(definition, value, expected)

    def test_independence_does_not_impose_a_fixed_team(self) -> None:
        cases = [
            (["builder-a", "builder-b"], ["qa-a", "qa-b"], True),
            ([], ["qa"], True),
            (["builder"], ["qa", "qa"], True),
            (["builder"], [], False),
            (["builder-a", "builder-b"], ["builder-b"], False),
            (["builder"], ["qa", "builder"], False),
            (["builder"], [""], False),
        ]
        for constructors, verifiers, expected in cases:
            with self.subTest(constructors=constructors, verifiers=verifiers):
                self.assert_accepts("#IndependentVerification", {
                    "constructors": constructors, "verifiers": verifiers,
                }, expected)

    def test_authority_matches_actor_action_and_target_without_inferred_grants(self) -> None:
        effect = {"actor": "worker", "action": "inspect", "target": "candidate"}
        grants = [{"effect": effect, "source": SOURCE}]
        cases = [(effect, True)]
        # Each independent scope dimension changes the verdict.
        for field, changed in (("actor", "parent"), ("action", "edit"), ("target", "other")):
            cases.append(({**effect, field: changed}, False))
        for proposed, expected in cases:
            with self.subTest(proposed=proposed):
                self.assert_accepts("#AuthorizedEffects", {"grants": grants, "proposed": [proposed]}, expected)
        self.assert_accepts("#AuthorizedEffects", {"grants": [], "proposed": []}, True)
        self.assert_accepts("#AuthorizedEffects", {"grants": [], "proposed": [effect]}, False)
        self.assert_accepts("#AuthorizedEffects", {
            "grants": grants + [{"effect": {**effect, "action": "edit"}, "source": SOURCE}],
            "proposed": [effect],
        }, True)
        self.assert_accepts("#AuthorizedEffects", {
            "grants": [{"effect": {**effect, "target": "candidate/*"}, "source": SOURCE}],
            "proposed": [effect],
        }, False)
        self.assert_accepts("#AuthorizedEffects", {
            "grants": [{"effect": effect}], "proposed": [effect],
        }, False)

    def test_source_reference_variants_are_shapes_not_resolved_resources(self) -> None:
        sources = [
            SOURCE,
            {"kind": "file", "path": "not-required-to-exist", "revision": "snapshot", "selector": "section"},
            {"kind": "message", "session": "s", "entry": "e"},
            {"kind": "ticket", "tracker": "local", "id": "t"},
            {"kind": "url", "url": "https://example.invalid/source"},
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assert_accepts("#SourceRef", source, True)
        for source in ({"kind": "file", "path": ""}, {"kind": "message", "session": "s"}, {"kind": "unknown"}):
            with self.subTest(source=source):
                self.assert_accepts("#SourceRef", source, False)

    def test_unresolved_is_not_false_or_a_fabricated_resolved_value(self) -> None:
        base = {"question": "Does the change require integration?", "sources": []}
        cases = [
            ({"status": "resolved", "value": False, "rationale": "The consumers are separate."}, True),
            ({"status": "resolved", "value": {"phase": "review"}, "rationale": "The task names it."}, True),
            ({"status": "unresolved", "missing": "The consumer contract has not been inspected."}, True),
            ({"status": "unresolved", "missing": "Need contract", "value": False}, False),
            ({"status": "resolved", "rationale": "No value supplied"}, False),
            ({"status": "resolved", "value": False}, False),
            ({"status": "unresolved"}, False),
        ]
        for judgment, expected in cases:
            with self.subTest(judgment=judgment):
                self.assert_accepts("#Judgment", {**base, **judgment}, expected)

    def test_coverage_accounts_for_inventory_without_turning_every_row_into_success(self) -> None:
        covered = {"status": "covered", "reason": "Component behavior was checked.", "evidence": [SOURCE]}
        for status in ("excluded", "unresolved", "unexamined", "covered"):
            row = {"status": status, "reason": "Declared disposition.", "evidence": [SOURCE] if status == "covered" else []}
            with self.subTest(status=status):
                self.assert_accepts("#Coverage", {
                    "inventory": ["component", "integration"],
                    "dispositions": {"component": covered, "integration": row},
                }, True)
        self.assert_accepts("#Coverage", {"inventory": [], "dispositions": {}}, True)
        self.assert_accepts("#Coverage", {"inventory": ["a", "a"], "dispositions": {"a": covered}}, True)
        self.assert_accepts("#Coverage", {"inventory": ["a", "b"], "dispositions": {"a": covered}}, False)
        self.assert_accepts("#Coverage", {"inventory": ["a"], "dispositions": {"a": covered, "b": covered}}, False)
        self.assert_accepts("#Coverage", {
            "inventory": ["a"], "dispositions": {"a": {**covered, "evidence": []}},
        }, False)

    def test_prerequisite_limits_only_its_dependent_action(self) -> None:
        forbidden = {(True, "unsatisfied", "proceed"), (True, "unresolved", "proceed")}
        for required, state, action in itertools.product(
            (False, True), ("satisfied", "unsatisfied", "unresolved"), ("proceed", "defer"),
        ):
            with self.subTest(required=required, state=state, action=action):
                self.assert_accepts("#Prerequisite", {
                    "required": required, "state": state, "dependentAction": action,
                }, (required, state, action) not in forbidden)


if __name__ == "__main__":
    unittest.main()
