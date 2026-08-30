#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname "$0")/../../.." && pwd)
test_directory=$(mktemp -d "${TMPDIR:-/tmp}/macos-preferences-tests.XXXXXX")
trap 'rm -rf "$test_directory"' EXIT HUP INT TERM

swiftc -DTESTING -parse-as-library \
	"$root/tools/macos-preferences/Sources/MacOSPreferences/MacOSPreferences.swift" \
	"$root/tools/macos-preferences/tests/TestMain.swift" \
	-o "$test_directory/tests"
"$test_directory/tests" "$root/config/macos.json"
