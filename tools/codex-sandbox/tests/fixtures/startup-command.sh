#!/bin/sh
set -eu
printf 'Startup boundary: agent command\n' >&2
exec "$@"
