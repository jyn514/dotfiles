"""Run the Bluesky likes tool's offline suite with its supported Node runtime."""


def test_bsky_gallery(run_native_suite):
    run_native_suite(["npm", "--prefix", "tools/search-bsky-likes", "test"])
