#!/bin/sh
set -eu
[ "$#" -eq 1 ] && [ "$1" = run ] || exit 91
pwd -P > "$DOTFILES_NVIM_FLIX_CWD_LOG"
exit "${DOTFILES_NVIM_FLIX_EXIT_STATUS:-0}"
