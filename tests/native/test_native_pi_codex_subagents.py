"""Run the isolated source-backed subagent phases, including local integrations."""


def test_pi_codex_subagents(run_native_suite):
    run_native_suite(["bun", "tools/pi-codex-subagents/test/run-source-tests.ts"])
