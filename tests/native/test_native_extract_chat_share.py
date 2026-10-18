"""Run the extract-chat-share Node suite."""


def test_extract_chat_share(run_native_suite):
    run_native_suite(["node", "tools/extract-chat-share/tests/extract_chat_share_test.js"])
