"""Discover the opt-in real Dashboard + native Pi/browser queue regression."""


def test_dashboard_queue(run_native_suite):
    run_native_suite(["node", "--test", "tests/pi/native_dashboard_queue.mjs"])
