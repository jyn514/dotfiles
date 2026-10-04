#!/bin/sh
exists() { test -x "$GLIDE_TEST_BIN/$1"; }
cmd_alias() { return 0; }
if [ "$GLIDE_TEST_PLATFORM" = macos ]; then
	install_macos_local
else
	install_glide_native
fi
exit "$?"
