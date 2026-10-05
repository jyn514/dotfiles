#!/bin/sh
set -eu

echo 'unexpected permission generation' >&2
exit "${CODEX_TEST_GENERATION_EXIT_STATUS:?}"
