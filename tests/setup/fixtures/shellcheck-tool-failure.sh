#!/bin/sh
case $SHELLCHECK_FIXTURE_MODE in
	failure) printf '%s\n' 'fixture ShellCheck failure' >&2; exit 2;;
	invalid-json) printf '%s\n' 'not JSON';;
	empty-failure) printf '%s\n' '[]'; exit 1;;
esac
