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
	printf '%s\n' '--instafail --numprocesses --force-sugar'
	exit 0
fi
line=$name
for argument do line="$line <$argument>"; done
printf '%s\n' "$line" >> "$TEST_LOG"
if [ "$name" = pytest ]; then
	printf 'dispatch-home <%s>\n' "$HOME" >> "$TEST_LOG"
	exit "${TEST_PYTEST_STATUS:-0}"
fi
if [ "$name" = python3 ] && [ "${1:-}" = tools/codex-sandbox/tests/image_runtime_integration.py ]; then
	exit "${TEST_PROBE_STATUS:-0}"
fi
