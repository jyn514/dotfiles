"""Preserve the grouped Pi session-title Node suite as one scheduled item."""


def test_pi_session_title(run_native_suite):
    run_native_suite([
        "node", "--test",
        "tests/pi/native_session_title.mjs",
        "tests/pi/native_session_reader_title.mjs",
    ])
