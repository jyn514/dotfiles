"""Run Pi-to-Codex conversion and native import acceptance tests."""


def test_pi_to_codex(run_native_suite):
    run_native_suite(["node", "--test", "tools/pi-to-codex/tests/pi_to_codex_test.mjs"])
