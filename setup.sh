#!/bin/sh
set -u
set -e
set -v

# base config
LOCAL="$HOME/.local/config"
CONFIG="$(realpath "$(dirname "$0")/config")"
for f in $(ls --quoting-style=shell-escape "$CONFIG"); do
	DEST="$HOME/.$f"
	if [ -L "$DEST" ]; then rm "$DEST"
	elif [ -e "$DEST" ]; then
			if ! [ -d "$LOCAL" ]; then mkdir "$LOCAL"; fi
			mv "$DEST" "$LOCAL"
	fi
	ln -s "$CONFIG/$f" "$DEST"
done
mkdir -p ~/.config/youtube-dl
mv ~/.youtube-dl ~/.config/youtube-dl/config

# may take a while
/usr/bin/env python -m pip install --user -r "$CONFIG/../python.txt"

VIMDIR="$HOME/.vim/autoload"
if ! [ -e "$VIMDIR/plug.vim" ]; then
	curl -Lo "$VIMDIR/plug.vim" --create-dirs \
		https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
fi

unset LOCAL CONFIG DEST VIMDIR
