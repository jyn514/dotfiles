"""Run the extract-chat Babashka suite."""


def test_extract_chat(run_native_suite):
    run_native_suite(["bb", "tools/extract-chat/tests/extract_chat_test.clj"])
