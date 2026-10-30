#!/bin/sh
set -eu
[ "$#" -eq 3 ] && [ "$1" = -L ] && [ "$2" = -- ] && [ "$3" = "package with spaces" ] || exit 23
printf '%s\n' "$PROFILE_TEST_PACKAGE_DATA" "$PROFILE_TEST_PACKAGE_EXECUTABLE"
