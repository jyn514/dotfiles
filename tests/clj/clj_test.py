import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/clj"
LOADER = importlib.machinery.SourceFileLoader("clj_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
clj = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = clj
LOADER.exec_module(clj)


class CljTests(unittest.TestCase):
    def test_adds_development_alias_before_user_arguments(self):
        runner = mock.Mock(
            side_effect=[clj.Result(0, b"[:test :dev :other]\n"), clj.Result(0)]
        )

        self.assertEqual(clj.launch(["argument with spaces"], runner), 0)
        self.assertEqual(
            runner.call_args_list,
            [
                mock.call(["clojure", "-X:deps", "aliases"], capture_output=True),
                mock.call(
                    [
                        "clojure",
                        "-J--enable-native-access=ALL-UNNAMED",
                        "-A:dev",
                        "argument with spaces",
                        "-Xrebel",
                    ]
                ),
            ],
        )

    def test_absent_alias_does_not_add_development_argument(self):
        runner = mock.Mock(
            side_effect=[clj.Result(0, b"[:test]\n"), clj.Result(17)]
        )

        self.assertEqual(clj.launch([], runner), 17)
        self.assertEqual(
            runner.call_args_list[-1],
            mock.call(
                ["clojure", "-J--enable-native-access=ALL-UNNAMED", "-Xrebel"]
            ),
        )

    def test_preserves_legacy_substring_match_without_decoding_output(self):
        runner = mock.Mock(
            side_effect=[clj.Result(0, b"invalid-\xff-prefix:dev-suffix"), clj.Result(0)]
        )

        self.assertEqual(clj.launch([], runner), 0)
        self.assertIn("-A:dev", runner.call_args_list[-1].args[0])

    def test_query_failure_discards_partial_output_and_does_not_launch(self):
        runner = mock.Mock(return_value=clj.Result(23, b":dev\n"))

        self.assertEqual(clj.launch(["argument"], runner), 23)
        runner.assert_called_once_with(
            ["clojure", "-X:deps", "aliases"], capture_output=True
        )

    def test_missing_clojure_returns_shell_compatible_status(self):
        with mock.patch.object(
            clj.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = clj.run(["clojure"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'clojure'", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
