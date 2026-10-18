"""Run the sandbox tool-worker Node suite."""


def test_tool_worker(run_native_suite):
    run_native_suite(["node", "--test", "tools/codex-sandbox/tests/tool_worker_test.mjs"])
