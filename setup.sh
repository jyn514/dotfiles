#!/bin/sh
set -e
set -v

# base config
LOCAL="$HOME/.local/config"
CONFIG=config
for f in "$CONFIG"/*; do
	if [ "$f" = "youtube-dl" ]; then
		DEST="$HOME/.config/youtube-dl/config"
	else
		DEST="$HOME/.$f"
	fi
	if [ -L "$DEST" ]; then rm "$DEST"
	elif [ -e "$DEST" ]; then
			if ! [ -d "$LOCAL" ]; then mkdir "$LOCAL"; fi
			mv "$DEST" "$LOCAL"
	fi
	ln -s "$CONFIG/$f" "$DEST"
done

setup_shell () {
	default_shell=$(grep "$USER" /etc/passwd | cut -d ':' -f 7)
	if   ! grep zsh "$default_shell"; then
		if which zsh ; then chsh -s "$(which zsh)" ; fi
	elif ! grep bash "$default_shell"; then
		if which bash; then chsh -s "$(which bash)"; fi
	fi
	unset default_shell
}

setup_shell

if [ -x "$(which pip)" ]; then
	PYTHON="$(which pip)"
elif [ -x "$(which python)" ] && "$(which python)" -m pip > /dev/null; then
	PYTHON="$(which python) -m pip"
fi

# may take a while
if ! [ -z "$PYTHON" ]; then
	$PYTHON install --user -r "$CONFIG/../python.txt"
fi

VIMDIR="$HOME/.vim/autoload"
if ! [ -e "$VIMDIR/plug.vim" ]; then
	curl -Lo "$VIMDIR/plug.vim" --create-dirs \
		https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
	vim -c PlugUpdate -c q -c q
fi

unset LOCAL CONFIG DEST VIMDIR
