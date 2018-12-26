#!/bin/sh
set -e

setup_basics () {
	LOCAL="$HOME/.local/config"
	if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
	for f in "$(realpath config)"/*; do
		if [ "$f" = "youtube-dl" ]; then
			DEST="$HOME/.config/youtube-dl/config"
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
	fi
	printf '\nPATH=%s:$PATH\n' "$(realpath ./bin)" >> ~/.profile
unset DEST LOCAL f
}

setup_shell () {
	default_shell=$(grep "$USER" /etc/passwd | cut -d ':' -f 7)
	for shell in zsh fish bash; do
		if echo "$default_shell" | grep $shell > /dev/null; then
			echo using current shell "$shell"
			break
		elif which $shell ; then
			chsh -s "$(which $shell)"
			break
		fi
	done
unset default_shell shell
}

setup_python () {
	if [ -x "$(which pip)" ]; then
		PIP="$(which pip)"
	elif [ -x "$(which python)" ] && "$(which python)" -m pip > /dev/null; then
		PIP="$(which python) -m pip"
	fi

	# may take a while
	if ! [ -z "$PIP" ]; then
		$PIP install --user -r python.txt
	else
		echo pip not found
	fi
unset PIP
}

setup_vim () {
VIMDIR="$HOME/.vim/autoload"
	if ! [ -e "$VIMDIR/plug.vim" ]; then
		curl -Lo "$VIMDIR/plug.vim" --create-dirs \
			https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
		vim -c PlugInstall -c q -c q
	fi
unset VIMDIR
}

setup_backup () {
	TMP_FILE=/tmp/tmp_cronjob
	which backup || { echo "need to run setup_basics first"; return 1; }
	# tried piping this straight to `crontab -`
	# it failed when non-interactive for some reason
	crontab -l > $TMP_FILE || true;  # ignore missing crontab
	echo '0 12 * * * backup' >> $TMP_FILE && crontab $TMP_FILE
	rm -f $TMP_FILE
	unset TMP_FILE
}

setup_all () {
	setup_basics
	setup_shell
	setup_python
	setup_vim
	setup_backup
	exit 0
}

cd "$(realpath "$(dirname "$0")")"
MESSAGE="[0] exit
[1] dotfiles
[2] shell
[3] python
[4] vim
[5] backup
[6] all
Choose setup to run: "

printf "$MESSAGE"
while read choice; do
	case $choice in
		q*|e*|0) exit 0;;
		dot*|bas*|1) setup_basics; printf "$MESSAGE";;
		sh*|2) setup_shell; printf "$MESSAGE";;
		py*|3) setup_python; printf "$MESSAGE";;
		vi*|4) setup_vim; printf "$MESSAGE";;
		bac*|5) setup_basics; setup_backup; printf "$MESSAGE";;
		all|6) setup_all;;
		*) printf "Please enter a number 0-6: ";;
	esac
done
