#!/bin/sh
exec "$DOTFILES_TEST_NVIM_REAL" --headless -u NONE -i NONE "$@" -c 'luafile '"$DOTFILES_TEST_NVIM_CAPTURE"
