"""Run the sandbox session-side Bun suite."""


def test_session_side(run_native_suite):
    run_native_suite(["bun", "test", "tools/codex-sandbox/tests/session_side_test.ts"])
