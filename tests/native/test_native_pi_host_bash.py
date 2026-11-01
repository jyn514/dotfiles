"""Exercise host and guest extension registration with the installed Pi loader."""


def test_pi_host_bash(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_host_bash.mjs"])
