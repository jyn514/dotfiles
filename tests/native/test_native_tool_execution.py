"""Exercise routed tools through the installed Pi runtime and guest worker."""


def test_tool_execution(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_tool_execution.mjs"])
    run_native_suite(["bun", "test", "./tests/pi/tool_execution_test.ts"])
