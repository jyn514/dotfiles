"""Exercise real Pi settlement and tools with the offline installed provider."""


def test_commit_boundary_session(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_commit_boundary.mjs"])
