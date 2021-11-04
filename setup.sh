#!/bin/sh
set -eu

setup_basics () {
	echo Installing configuration to ~
	LOCAL="$HOME/.local/config"
	if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
	for f in "$(realpath config)"/*; do
		base="$(basename "$f")"
		if [ "$base" = "youtube-dl" ]; then
			DEST="$HOME/.config/youtube-dl/config"
		elif [ "$base" = "config.fish" ]; then
			DEST="$HOME/.config/fish/$base"
		elif [ "$base" = openbox.xml ]; then
			DEST="$HOME/.config/openbox/lubuntu-rc.xml"
		elif [ "$base" = grepme.toml ]; then
			DEST="$HOME/.config/$base"
		elif [ "$base" = kitty.conf ]; then
			DEST="$HOME/.config/kitty/$base"
		else
			DEST="$HOME/.$base"
		fi
		if [ -L "$DEST" ]; then rm -f "$DEST"
		elif [ -e "$DEST" ]; then
				mv "$DEST" "$LOCAL"
		fi
		mkdir -p "$(dirname "$DEST")"
		ln -s "$(realpath "$f")" "$DEST"
	done
	if gpg -K | grep ultimate > /dev/null; then
		mkdir -p ~/.config/git
		echo '
[commit]
	gpgsign = true' >> ~/.config/git/config
	else
		echo not setting up GPG-signed commits, no ultimate key found
	fi
	# don't break when sourcing .bashrc
	if alias | grep -q ' ls='; then unalias ls; fi
	if [ "$HAS_REALPATH" = 0 ]; then
		grep -v 'set -.*e' < lib/realpath.sh >> ~/.local/profile
	fi
	set +ue
	. ~/.profile
	setup_vim # otherwise vim will error out the next time it starts up
unset DEST LOCAL f
}

setup_shell () {
	echo Changing default shell
	for shell in zsh fish bash; do
		if echo "$SHELL" | grep $shell; then
			echo using current shell "$shell"
			break
		elif exists $shell; then
			chsh -s "$(command -v $shell)"
			break
		fi
	done
unset shell
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
	elif exists su; then
		su root -c ./lib/setup_sudo.sh
	else
		./lib/setup_sudo.sh
	fi
	echo Installing user packages
	mkdir -p ~/.local/bin
	if ! [ -x ~/.local/bin/cat ]; then ln -sf "$(command -v bat)" ~/.local/bin/cat; fi
	if ! [ -x ~/.local/bin/python ]; then ln -sf "$(command -v python3)" ~/.local/bin/python; fi
	if ! exists pip && exists pip3; then ln -sf "$(command -v pip3)" ~/.local/bin/pip; fi
	ln -sf "$(realpath bin/reinstall-ra)" ~/.local/bin
	install_rust
}

install_rust() {
	if ! exists code; then
		download https://go.microsoft.com/fwlink/?LinkID=760868 code.deb
		sudo apt install ./code.deb
	fi
	code --install-extension vscodevim.vim
	code --install-extension matklad.rust-analyzer
	set +ue
	. config/profile
	set -ue
	if ! exists cargo; then
		t=/tmp/rustup-init.sh
		curl https://sh.rustup.rs/ > $t && sh $t -y --profile minimal -c rustfmt -c clippy && rm $t
		. "$CARGO_HOME/env"
		rustup toolchain add nightly --profile minimal -c clippy -c miri
		rustup default nightly
		unset t
	fi
	mkdir -p ~/src/rust && cd ~/src/rust
	for repo in https://github.com/rust-lang/docs.rs https://github.com/rust-lang/rust; do
		if ! [ -e "$(basename $repo)" ]; then
			git clone $repo
		fi
	done
	cd "$OLDPWD"
	# avoid recompiling so much
	CARGO_TARGET_DIR=/tmp/cargo
	mkdir -p $CARGO_TARGET_DIR
	cargo install broot cargo-audit cargo-outdated cargo-sweep cargo-tree cargo-edit
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

cd "$(dirname "$0")"
. lib/lib.sh
if ! exists realpath; then
	. lib/realpath.sh
	HAS_REALPATH=0
else
	HAS_REALPATH=1
fi

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
