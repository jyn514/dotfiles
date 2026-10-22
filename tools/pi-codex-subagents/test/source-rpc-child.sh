#!/bin/sh
# The parent test bootstrap owns both the executable and the source alias config.
set -eu
: "${PI_TEST_BUN:?run through test/run-source-tests.ts}"
: "${PI_TEST_CORE_TSCONFIG:?run through test/run-source-tests.ts}"
entry=source-rpc-child.ts
if [ "${PI_TEST_CHECKPOINT_FILTER:-}" = 1 ]; then entry=checkpoint-rpc-filter.ts; fi
exec "$PI_TEST_BUN" --no-install --tsconfig-override="$PI_TEST_CORE_TSCONFIG" "$(dirname "$0")/$entry" "$@"
