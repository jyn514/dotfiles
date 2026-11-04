"""Exercise edit diagnostics and the configured native bundle offline."""


def test_pi_edit_suggestions(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_edit_suggestions.mjs"])
