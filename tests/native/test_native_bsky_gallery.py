"""Run the Bluesky gallery's offline JavaScript regression suite."""


def test_bsky_gallery(run_native_suite):
    run_native_suite(["bun", "test", "tools/search-bsky-likes/tests"])
