"""Run the package-plan Babashka suite."""


def test_package_plan(run_native_suite):
    run_native_suite([
        "bb", "-cp", "tools/package-plan/src", "tools/package-plan/tests/run.clj",
    ])
