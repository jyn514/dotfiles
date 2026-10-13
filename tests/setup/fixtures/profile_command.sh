#!/bin/sh
# Load the actual interactive profile before exercising its commands.
# Sourced helpers also support direct invocation, so hide the fixture arguments.
profile_test_initialize() {
	set --
	. "$HOME/.profile"
}
profile_test_initialize || exit
if [ -n "${PROFILE_TEST_BIN:-}" ]; then
	PATH="$PROFILE_TEST_BIN:$PATH"
	export PATH
fi
profile_test_command=$1
shift
eval "$profile_test_command"
