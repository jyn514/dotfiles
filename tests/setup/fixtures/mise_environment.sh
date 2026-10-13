#!/bin/sh
set -eu
[ "$*" = 'env --shell bash' ] || exit 2
printf 'export DOTFILES_MISE_ENV_APPLIED=yes\n'
exit "${DOTFILES_MISE_ENV_EXIT:-0}"
