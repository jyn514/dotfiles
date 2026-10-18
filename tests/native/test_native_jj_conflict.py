"""Run the agent-wrapper Jujutsu conflict Node suite."""


def test_jj_conflict(run_native_suite):
    run_native_suite(["node", "--test", "tests/agent-wrappers/jj-conflict.test.mjs"])
