#!/bin/sh
# The command must really run inside the runner's PTY, not a fake runner.
if [ "$1" = pty ]; then
	test -t 1 || exit 99
	shift
fi
printf 'native output\n'
case "$1" in
	TERM) kill -TERM "$$" ;;
	INT) kill -INT "$$" ;;
	*) exit "$1" ;;
esac
