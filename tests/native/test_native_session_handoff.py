"""Run the sandbox session-handoff Bun suite."""


def test_session_handoff(run_native_suite):
    run_native_suite(["bun", "test", "tools/codex-sandbox/tests/session_handoff_test.ts"])
