"""Run the agent-split Babashka suite."""

import os


def test_agent_split(run_native_suite):
    env = {}
    if real_jj := os.environ.get("DOTFILES_TEST_JJ_REAL"):
        env["JJ_REAL"] = real_jj
    run_native_suite(
        ["bb", "-cp", "tools/agent-split/src", "tools/agent-split/tests/run.clj"],
        env=env,
    )
