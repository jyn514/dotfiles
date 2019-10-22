#!/bin/sh
set -eu

startswith() {
	case "$1" in
		"$2"*) return 0;;
		*) return 1;;
	esac
}

realdir() {
	cd "$1" && pwd -P
}

command -v realpath >/dev/null 2>&1 || realpath() {
	if [ -d "$1" ]; then
		realdir "$1"
		return
	fi
	dir="$(realdir "$(dirname "$1")")"
	if [ -L "$1" ]; then
		file="$(readlink "$1")"
	else
		file="$1"
	fi
	# absolute path, ignore directory
	if startswith "$file" /; then
		echo "$file"
		return
	fi
	echo "$dir/$file"
}

setup_basics () {
	echo Installing configuration to ~
	LOCAL="$HOME/.local/config"
	if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
	for f in "$(realpath config)"/*; do
		base="$(basename "$f")"
		if [ "$base" = "youtube-dl" ]; then
			DEST="$HOME/.config/youtube-dl/config"
		elif [ "$base" = "config.fish" ]; then
			DEST="$HOME/.config/fish/config.fish"
		else
			DEST="$HOME/.$(basename "$f")"
		fi
		if [ -L "$DEST" ]; then rm -f "$DEST"
		elif [ -e "$DEST" ]; then
				mv "$DEST" "$LOCAL"
		fi
		mkdir -p "$(dirname "$DEST")"
		ln -s "$(realpath "$f")" "$DEST"
	done
	if gpg -K | grep ultimate > /dev/null; then
		echo '
[commit]
	gpgsign = true' >> ~/.config/git/config
	else
		echo not setting up GPG-signed commits, no ultimate key found
	fi
	# don't break when sourcing .bashrc
	if alias | grep -q ' ls='; then unalias ls; fi
	set +ue
	. ~/.profile
unset DEST LOCAL f
}

setup_shell () {
	echo Changing default shell
	default_shell=$(grep "$USER" /etc/passwd | cut -d ':' -f 7)
	for shell in zsh fish bash; do
		if echo "$default_shell" | grep $shell > /dev/null; then
			echo using current shell "$shell"
			break
		elif exists shell; then
			chsh -s "$(command -v $shell)"
			break
		fi
	done
unset default_shell shell
}

setup_python () {
	echo Installing python packages in python.txt
	if [ -x "$(command -v pip)" ]; then
		PIP="$(command -v pip)"
	elif [ -x "$(command -v python)" ] && "$(command -v python)" -m pip > /dev/null; then
		PIP="$(command -v python) -m pip"
	fi

	# may take a while
	if [ -n "$PIP" ]; then
		$PIP install --user -r python.txt
	else
		echo pip not found
	fi
unset PIP
}

setup_vim () {
	echo Installing vim plugins
VIMDIR="$HOME/.vim/autoload"
	if ! [ -e "$VIMDIR/plug.vim" ]; then
		mkdir -p "$VIMDIR"
		download https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim "$VIMDIR/plug.vim"
	fi
	vim -c PlugInstall -c q -c q
unset VIMDIR
}

setup_backup () {
	echo Setting up daily backup
	TMP_FILE=/tmp/tmp_cronjob
	exists backup || { echo "need to run setup_basics first"; return 1; }
	# tried piping this straight to `crontab -`
	# it failed when non-interactive for some reason
	crontab -l > $TMP_FILE 2>/dev/null || true;  # ignore missing crontab
	echo '0 12 * * * backup' >> $TMP_FILE && crontab $TMP_FILE
	rm -f $TMP_FILE
	unset TMP_FILE
}

setup_install () {
	echo Installing global packages
	if exists sudo; then
		sudo ./lib/setup_sudo.sh
	else
		su root -c ./lib/setup_sudo.sh;
	fi
	echo Installing user packages
	if ! { exists keepassxc || [ -x bin/keepassxc ]; }; then
		download "https://github.com/keepassxreboot/keepassxc/releases/download/2.3.4/KeePassXC-2.3.4-x86_64.AppImage" keepassxc
		mv keepassxc bin
		chmod +x bin/keepassxc
		bin/keepassxc >/dev/null 2>&1 &
	fi
	mkdir -p ~/.local/bin
	if ! [ -x ~/.local/bin/cat ]; then ln -sf "$(command -v bat)" ~/.local/bin/cat; fi
	if ! [ -x ~/.local/bin/python ]; then ln -sf "$(command -v python3)" ~/.local/bin/python; fi
	if ! exists pip && exists pip3; then ln -sf "$(command -v pip3)" ~/.local/bin/pip; fi
}

setup_all () {
	echo Doing everything
	setup_install  # so we know we have vim, git, etc.
	setup_basics
	setup_shell
	setup_python
	setup_vim
	setup_backup
	exit 0
}

message () {
	printf "%s" "[0] exit
[1] dotfiles
[2] shell
[3] python
[4] vim
[5] backup
[6] install (uses sudo)
[7] all
Choose setup to run: "
}

# main

cd "$(realpath "$(dirname "$0")")"
. lib/lib.sh

message
while read -r choice; do
	case $choice in
		q*|e*|0) exit 0;;
		dot*|bas*|1) setup_basics; message;;
		sh*|2) setup_shell; message;;
		py*|3) setup_python; message;;
		vi*|4) setup_vim; message;;
		bac*|5) setup_basics; setup_backup; message;;
		su*|i*|6) setup_install; message;;
		all|7) setup_all; exit 0;;
		*) printf "Please enter a number 0-6: ";;
	esac
done
