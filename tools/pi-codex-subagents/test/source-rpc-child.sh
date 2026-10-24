#!/bin/sh
# The parent test bootstrap owns both the executable and the source alias config.
set -eu
: "${PI_TEST_BUN:?run through test/run-source-tests.ts}"
: "${PI_TEST_CORE_TSCONFIG:?run through test/run-source-tests.ts}"
exec "$PI_TEST_BUN" --no-install --tsconfig-override="$PI_TEST_CORE_TSCONFIG" "$(dirname "$0")/source-rpc-child.ts" "$@"
