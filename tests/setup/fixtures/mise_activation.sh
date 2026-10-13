#!/bin/sh
set -eu
for name in MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH; do
	if printenv "$name" >/dev/null; then exit 19; fi
done
case "$1:$2" in
	activate:bash|activate:zsh|env:--shell)
		printf '%s\n' 'export DOTFILES_MISE_ACTIVE=yes' 'export PATH="$PROFILE_MISE_TOOLS:$PATH"'
		;;
	activate:fish|hook-env:--shell)
		printf '%s\n' 'set -gx DOTFILES_MISE_ACTIVE yes' 'set -gx PATH "$PROFILE_MISE_TOOLS" $PATH'
		;;
	*) exit 2;;
esac
