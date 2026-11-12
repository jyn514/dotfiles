"""Exercise the production BPF access policy with disposable native-C task models."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="proc-policy-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.program = Path(cls.temporary.name) / "policy"
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("cc is required for the proc-read-guard policy tests")
        build = subprocess.run([
            compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wno-unknown-pragmas", "-I", str(HERE / "fixtures"),
            str(HERE / "policy_harness.c"), "-o", str(cls.program),
        ], capture_output=True, text=True, timeout=60)
        if build.returncode:
            raise RuntimeError(build.stdout + build.stderr)

    def decision(self, scenario, *arguments):
        result = subprocess.run(
            [str(self.program), scenario, *map(str, arguments)],
            text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return int(result.stdout)

    def test_group_credentials_exempt_sibling_reads(self):
        for scenario in ("real-group", "effective-group", "saved-group",
                         "filesystem-group", "inherited-group"):
            with self.subTest(scenario=scenario):
                self.assertEqual(0, self.decision(scenario))

    def test_group_exemption_is_not_restricted_to_parent_targets(self):
        for scenario in ("trusted-parent-target", "trusted-unrelated-target"):
            with self.subTest(scenario=scenario):
                self.assertEqual(0, self.decision(scenario))

    def test_ordinary_and_renamed_processes_remain_denied(self):
        for scenario in ("ordinary", "renamed-impostor"):
            with self.subTest(scenario=scenario):
                self.assertEqual(-1, self.decision(scenario))

    def test_missing_optional_group_disables_the_exemption(self):
        self.assertEqual(-1, self.decision("disabled-group"))

    def test_gid_zero_is_not_confused_with_disabled_configuration(self):
        self.assertEqual(0, self.decision("root-group"))

    def test_group_exemption_never_overrides_an_existing_denial(self):
        self.assertEqual(-13, self.decision("prior-denial"))

    def test_read_mode_with_other_flags_still_uses_group_exemption(self):
        self.assertEqual(0, self.decision("read-fscreds"))

    def test_existing_allowed_cases_are_unchanged(self):
        for scenario in ("attach", "same-process", "parent-reader",
                         "threaded-parent-reader", "other-caller-uid",
                         "root-caller", "other-target-uid"):
            with self.subTest(scenario=scenario):
                self.assertEqual(0, self.decision(scenario))

    def test_existing_ancestry_bound_is_unchanged(self):
        for depth, expected in ((1, 0), (16, 0), (17, -1), (33, -1)):
            with self.subTest(depth=depth):
                self.assertEqual(expected, self.decision("ancestor", depth))

    def test_supplementary_membership_including_kernel_maximum_group_count(self):
        for count in (0, 1, 2, 17, 64, 65536):
            members = {100 + 2 * index for index in (0, count // 2, count - 1)} if count else set()
            absent = {99, 101, 100 + 2 * count}
            for gid in members | absent:
                with self.subTest(count=count, gid=gid):
                    expected = 0 if gid in members else -1
                    self.assertEqual(expected, self.decision("supplementary", count, gid))


if __name__ == "__main__":
    unittest.main()
