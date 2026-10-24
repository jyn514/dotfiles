#!/bin/sh
exists() { test -x "$GLIDE_TEST_BIN/$1"; }
if [ "$GLIDE_TEST_PLATFORM" = macos ]; then
	exit 0
fi
install_dragon_native
exit "$?"
