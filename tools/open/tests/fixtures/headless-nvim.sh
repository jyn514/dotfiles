#!/bin/sh

# The test prepends this adapter so a bare REAL_EDITOR selects it. Remove that
# entry before the repository nvim shim resolves the installed native binary.
script_dir=$(dirname -- "$0") || exit
adapter_dir=$(CDPATH='' cd -- "$script_dir" && pwd -P) || exit
case $PATH in
	"$adapter_dir":*) PATH=${PATH#*:} ;;
	*) echo "headless nvim adapter is not first on PATH" >&2; exit 1 ;;
esac
export PATH

exec "$DOTFILES_TEST_NVIM_REAL" --headless -u NONE -i NONE "$@" -c 'luafile '"$DOTFILES_TEST_NVIM_CAPTURE"
