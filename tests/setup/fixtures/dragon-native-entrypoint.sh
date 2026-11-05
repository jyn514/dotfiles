#!/bin/sh
# shellcheck disable=SC2329 # The production function appended by the test calls this fixture.
exists() { test -x "$GLIDE_TEST_BIN/$1"; }
if [ "$GLIDE_TEST_PLATFORM" = macos ]; then
	exit 0
fi
install_dragon_native
exit "$?"
