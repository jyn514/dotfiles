#!/bin/sh
set -eu
name=${0##*/}
if [ "$name" = python3 ]; then
	case ${1:-} in
		*/tools/codex-sandbox/owned_images.py)
			printf 'metadata-home <%s>\n' "$HOME" >> "$TEST_LOG"
			printf 'metadata-helper <%s>\n' "$1" >> "$TEST_LOG"
			exec "$TEST_PYTHON_REAL" "$@"
			;;
		*/dev/test-environment) exec "$TEST_PYTHON_REAL" "$@";;
	esac
fi
if [ "$name" = pytest ] && [ "${1:-}" = --help ]; then
	if [ "${TEST_BROKEN_PYTEST:-0}" = 1 ]; then
		echo 'ModuleNotFoundError: No module named pytest' >&2
		exit 1
	fi
	if [ "${TEST_MISSING_PYTEST_PLUGIN:-0}" = 1 ]; then
		printf '%s\n' '--instafail --numprocesses'
	else
		printf '%s\n' '--instafail --numprocesses --force-sugar'
	fi
	exit 0
fi
if [ "$name" = uvx ]; then
	printf '%s\n' "$@" > "$TEST_ARGV_LOG"
	exit 23
fi
line=$name
for argument do line="$line <$argument>"; done
printf '%s\n' "$line" >> "$TEST_LOG"
if [ "$name" = python3 ] && [ "${1:-}" = dev/check-shell.py ]; then
	exit "${TEST_SHELLCHECK_STATUS:-0}"
fi
if [ "$name" = pytest ]; then
	printf 'dispatch-home <%s>\n' "$HOME" >> "$TEST_LOG"
	if [ -n "${TEST_ARGV_LOG:-}" ]; then
		printf '%s\n' "$@" > "$TEST_ARGV_LOG"
	fi
	exit "${TEST_PYTEST_STATUS:-0}"
fi
if [ "$name" = python3 ] && [ "${1:-}" = tools/codex-sandbox/tests/image_runtime_integration.py ]; then
	exit "${TEST_PROBE_STATUS:-0}"
fi
