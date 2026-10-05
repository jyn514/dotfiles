#!/bin/sh
"$REAL_DIRNAME" "$@"
echo "fixture: dirname failed after publishing a path" >&2
exit 41
