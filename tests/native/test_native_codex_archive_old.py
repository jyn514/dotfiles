"""Run the codex-archive-old Node suite."""


def test_codex_archive_old(run_native_suite):
    run_native_suite(["node", "tools/codex-archive-old/tests/codex_archive_old_test.js"])
