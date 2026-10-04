#!/bin/sh
# Disposable setup commands: never elevate or install anything.
case ${0##*/} in
	id) printf '1000\n';;
	bb) exit 0;;
	sudo)
		printf 'fixture: sudo is running\n' >&2
		printf '%s\n' "$@"
		cat
		exit "${SUDO_TEST_STATUS:-0}"
		;;
esac
