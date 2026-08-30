#!/bin/sh
set -eu

[ "$(uname -s)" = Darwin ] || {
	echo "run-disposable-domain: macOS is required" >&2
	exit 1
}

root=$(CDPATH='' cd -- "$(dirname "$0")/../../.." && pwd)
fixture="$root/tools/macos-preferences/tests/disposable-policy.json"
test_directory=$(mktemp -d "${TMPDIR:-/tmp}/macos-preferences-e2e.XXXXXX")
domain="com.jyn.dotfiles.macos-preferences-test.${test_directory##*.}"
policy="$test_directory/policy.json"
owns_domain=0

cleanup() {
	status=$1
	trap - EXIT HUP INT TERM
	if [ "$owns_domain" -eq 1 ]; then
		if ! defaults delete "$domain" >/dev/null; then
			echo "run-disposable-domain: failed to delete $domain" >&2
			status=1
		fi
	fi
	rm -rf "$test_directory"
	exit "$status"
}
trap 'cleanup "$?"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if defaults read "$domain" >/dev/null 2>&1; then
	echo "run-disposable-domain: refusing to overwrite existing domain $domain" >&2
	exit 1
fi

jq --arg domain "$domain" \
	-f "$root/tools/macos-preferences/tests/rename-domain.jq" \
	"$fixture" >"$policy"
swiftc -parse-as-library \
	"$root/tools/macos-preferences/Sources/MacOSPreferences/MacOSPreferences.swift" \
	-o "$test_directory/macos-preferences"

owns_domain=1
"$test_directory/macos-preferences" apply "$policy"

defaults export "$domain" "$test_directory/actual.plist"
plutil -convert json -o "$test_directory/actual.json" "$test_directory/actual.plist"
jq -e -s \
	-f "$root/tools/macos-preferences/tests/verify-domain.jq" \
	"$policy" "$test_directory/actual.json" >/dev/null
"$test_directory/macos-preferences" check "$policy"
