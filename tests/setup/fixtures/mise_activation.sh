#!/bin/sh
set -eu
for name in MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH; do
	if printenv "$name" >/dev/null; then exit 19; fi
done
case "$1:$2" in
	activate:bash|activate:zsh|env:--shell)
		# shellcheck disable=SC2016 # Emit code for the caller to expand later.
		printf '%s\n' 'export DOTFILES_MISE_ACTIVE=yes' 'export PATH="$PROFILE_MISE_TOOLS:$PATH"'
		;;
	activate:fish|hook-env:--shell)
		# shellcheck disable=SC2016 # Emit Fish code for the caller to expand later.
		printf '%s\n' 'set -gx DOTFILES_MISE_ACTIVE yes' 'set -gx PATH "$PROFILE_MISE_TOOLS" $PATH'
		;;
	*) exit 2;;
esac
