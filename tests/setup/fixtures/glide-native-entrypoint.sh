#!/bin/sh
# shellcheck disable=SC2329 # The production functions appended by the test call these fixtures.
exists() { test -x "$GLIDE_TEST_BIN/$1"; }
cmd_alias() { return 0; }
if [ "$GLIDE_TEST_PLATFORM" = macos ]; then
	install_macos_local
else
	install_glide_native
fi
exit "$?"
