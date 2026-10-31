"""Run the sandbox tool-worker suite under its production Bun runtime."""


def test_tool_worker(run_native_suite):
    run_native_suite(["bun", "test", "tools/codex-sandbox/tests/tool_worker_test.mjs"])
