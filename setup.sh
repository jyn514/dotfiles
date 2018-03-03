#!/bin/sh
set -e
set -v

setup_basics () {
	LOCAL="$HOME/.local/config"
	for f in "$(realpath config)"/*; do
		if [ "$f" = "youtube-dl" ]; then
			DEST="$HOME/.config/youtube-dl/config"
		else
			DEST="$HOME/.$(basename $f)"
		fi
		if [ -L "$DEST" ]; then rm -f "$DEST"
		elif [ -e "$DEST" ]; then
				if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
				mv "$DEST" "$LOCAL"
		fi
		ln -s "$f" "$DEST"
	done
unset DEST LOCAL f
}

setup_shell () {
	default_shell=$(grep "$USER" /etc/passwd | cut -d ':' -f 7)
	if   ! grep zsh "$default_shell"; then
		if which zsh ; then chsh -s "$(which zsh)" ; fi
	elif ! grep bash "$default_shell"; then
		if which bash; then chsh -s "$(which bash)"; fi
	fi
unset default_shell
}

setup_python () {
	if [ -x "$(which pip)" ]; then
		PYTHON="$(which pip)"
	elif [ -x "$(which python)" ] && "$(which python)" -m pip > /dev/null; then
		PYTHON="$(which python) -m pip"
	fi

	# may take a while
	if ! [ -z "$PYTHON" ]; then
		$PYTHON install --user -r python.txt
	fi
unset PYTHON
}

setup_vim () {
VIMDIR="$HOME/.vim/autoload"
	if ! [ -e "$VIMDIR/plug.vim" ]; then
		curl -Lo "$VIMDIR/plug.vim" --create-dirs \
			https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
		vim -c PlugUpdate -c q -c q
	fi
unset VIMDIR
}

cd "$(realpath "$(dirname "$0")")"
setup_basics
setup_shell
setup_python
setup_vim
