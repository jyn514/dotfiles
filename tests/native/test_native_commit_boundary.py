"""Run commit-boundary regressions through the real Pi tools and local JJ."""


def test_commit_boundary(run_native_suite):
    run_native_suite(["bun", "test", "tools/codex-sandbox/tests/commit_boundary_test.ts"])
