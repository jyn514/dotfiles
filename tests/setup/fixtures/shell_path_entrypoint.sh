#!/bin/sh
set -eu
operation=$1
library=$2
shift 2
# The tests select and check each real library separately.
# shellcheck source=/dev/null
. "$library"
if [ "$operation" = alias ]; then
	cmd_alias "$@"
elif [ "$operation" = profile ]; then
	printf '%s\0' "$XDG_CONFIG_HOME" "$CARGO_HOME" "$RUSTUP_HOME" "$GOPATH" "$GOBIN" "$CARGO_TARGET_DIR"
fi
