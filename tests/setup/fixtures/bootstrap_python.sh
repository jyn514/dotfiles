#!/bin/sh
set -eu
export DOTFILES_PYTHON_EXECUTABLE="$0"
exec "$DOTFILES_TEST_PYTHON" "$@"
