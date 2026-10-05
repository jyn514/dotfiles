#!/bin/sh
set -eu
name=${0##*/}
if [ "$name" = pytest ] && [ "${1:-}" = --help ]; then
	printf '%s\n' '--instafail --numprocesses --force-sugar'
	exit 0
fi
printf '%s' "$name" >> "$TEST_LOG"
for argument do printf ' <%s>' "$argument" >> "$TEST_LOG"; done
printf '\n' >> "$TEST_LOG"
if [ "$name" = bun ] && [ "${1:-}" = test ] && [ "${2:-}" = tests/pi ]; then
	exit "${PI_TEST_STATUS:-0}"
fi
