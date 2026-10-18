"""Run the Pi prompt-history Node suite without subprocess test isolation."""


def test_pi_prompt_history(run_native_suite):
    run_native_suite([
        "node", "--test", "--test-isolation=none", "tests/pi/native_prompt_history.mjs",
    ])
