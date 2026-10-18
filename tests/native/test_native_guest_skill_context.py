"""Run the sandbox guest-skill-context Node suite."""


def test_guest_skill_context(run_native_suite):
    run_native_suite([
        "node", "--test", "tools/codex-sandbox/tests/guest_skill_context_test.mjs",
    ])
