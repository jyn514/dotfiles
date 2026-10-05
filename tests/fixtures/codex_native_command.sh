#!/bin/sh
set -eu

printf '%s\n' "$@"
exit "${CODEX_TEST_EXIT_STATUS:?}"
