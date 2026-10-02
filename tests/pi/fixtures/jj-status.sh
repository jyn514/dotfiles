#!/bin/sh
set -eu
[ "$#" -eq 3 ]
# The sandbox wrapper authorizes the command using the first argument.
[ "$1" = status ]
[ "$2" = --no-pager ]
[ "$3" = --color=never ]
cat jj-status.stdout
cat jj-status.stderr >&2
code=$(cat jj-status.code)
exit "$code"
