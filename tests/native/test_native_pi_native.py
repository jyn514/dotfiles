"""Preserve the grouped Pi native Node suite as one scheduled item."""


def test_pi_native(run_native_suite):
    run_native_suite([
        "node", "--test",
        "tests/pi/native_compact_session.mjs",
        "tests/pi/native_prompt_sections.mjs",
        "tests/pi/native_web_search.mjs",
        "tests/pi/native_subscription_usage.mjs",
        "tests/pi/native_validate_skill.mjs",
        "tests/pi/native_work_selection.mjs",
        "tests/pi/native_transport_diagnostics.mjs",
    ])
