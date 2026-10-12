#!/bin/sh
"$REAL_REALPATH" "$@"
echo "fixture: realpath failed after publishing a path" >&2
exit 41
