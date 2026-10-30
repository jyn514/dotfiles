#!/bin/sh
set -eu

if [ "${0##*/}" = sed ]; then
	echo FAILED_TRANSFORMATION_MUST_NOT_BE_CONSUMED
	echo injected-sed-failure >&2
	exit 24
fi

if [ "$1:$2" = "$FAIL_OPERATION" ]; then
	echo FAILED_OUTPUT_MUST_NOT_BE_CONSUMED
	echo injected-dconf-failure >&2
	exit 23
fi
if [ "$1" = read ]; then
	echo "['/test/selected/']"
else
	printf '[example]\nname=\047successful earlier output\047\n'
fi
