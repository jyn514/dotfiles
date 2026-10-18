"""Run the Pi Bun suite with its native directory discovery."""


def test_pi_bun(run_native_suite):
    run_native_suite(["bun", "test", "tests/pi"])
