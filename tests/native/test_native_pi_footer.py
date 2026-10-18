"""Run the Pi native-footer Node suite."""


def test_pi_footer(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_footer.mjs"])
