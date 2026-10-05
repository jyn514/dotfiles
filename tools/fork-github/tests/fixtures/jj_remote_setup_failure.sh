#!/bin/sh
if [ "$1 $2 $3" = "git remote add" ]; then
  echo "fixture: remote setup failed" >&2
  exit 23
fi
exec "$REAL_JJ" "$@"
