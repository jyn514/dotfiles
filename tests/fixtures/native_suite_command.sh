#!/bin/sh
set -eu
exec "$TEST_REAL_PYTHON" "$TEST_NATIVE_FIXTURE" "${0##*/}" "$@"
