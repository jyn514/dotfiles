"""Run the sandbox guest-tools Bun suite."""


def test_guest_tools(run_native_suite):
    run_native_suite(["bun", "test", "tools/codex-sandbox/tests/guest_tools_test.ts"])
