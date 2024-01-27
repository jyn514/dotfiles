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

setup_install_global () {
	echo Installing global packages
	if exists sudo; then
		sudo ./lib/setup_sudo.sh
	elif exists su; then
		su root -c ./lib/setup_sudo.sh
	else
		./lib/setup_sudo.sh
	fi
}

setup_install_local () {
	echo Installing user packages
	mkdir -p ~/.local/bin

	install_rust
	python3 -m pip install --user git-revise

	if ! [ -x ~/.local/bin/cat ] && exists bat; then ln -sf "$(command -v bat)" ~/.local/bin/cat; fi
	# On MacOS, XCode does weird shenanigans and looks at the command name >:(
	if ! [ -x ~/.local/bin/python ] && exists python3; then
		echo 'exec python3 "$@"' > ~/.local/bin/python
		chmod +x ~/.local/bin/python
	fi
	if ! exists pip && exists pip3; then ln -sf "$(command -v pip3)" ~/.local/bin/pip; fi
	ln -sf "$(realpath bin/reinstall-ra)" ~/.local/bin
}

install_rust() {
	if exists code; then
		for ext in vscodevim.vim rust-lang.rust-analyzer eamodio.gitlens ms-vscode-remote.remote-ssh \
				   tamasfe.even-better-toml ms-vscode.powershell ms-python.python redhat.vscode-yaml
		do
			code --install-extension $ext
		done
	fi

	set +ue
	. config/profile
	set -ue

	if ! exists cargo; then
		# Rustup unfortunately doesn't have a way for us to ask it to install the MSVC build tools for us.
		# Do it manually here.
		if [ "${OSTYPE:-}" = msys ]; then
			t=/tmp/vs_community.exe
			curl -L "https://aka.ms/vs/17/release/vs_community.exe" -o $t
			$t --wait --focusedUi --addProductLang En-us --add "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" --add "Microsoft.VisualStudio.Component.Windows11SDK.22000"
			rm $t
		fi
		t=/tmp/rustup-init.sh
		curl https://sh.rustup.rs/ > $t && sh $t -y --profile minimal -c rustfmt -c clippy && rm $t
		if [ "${OSTYPE:-}" = msys ]; then
			PATH="$PATH:${CARGO_HOME:-$HOME/.cargo}/bin"
		else
			. "${CARGO_HOME:-$HOME/.cargo}/env"
		fi
		rustup toolchain add nightly --profile minimal -c clippy -c miri
		rustup default nightly
		unset t
	fi
	mkdir -p ~/src && cd ~/src
	for repo in docs.rs rustc-dev-guide rust; do
		if ! [ -e $repo ]; then
			fork_github rust-lang/$repo
			command cd ..
		fi
	done
	if ! exists x; then
		cargo install --path rust/src/tools/x
	fi
	cd "$OLDPWD"
	# avoid recompiling so much
	export CARGO_TARGET_DIR=/tmp/cargo
	mkdir -p $CARGO_TARGET_DIR
	if ! exists cargo-binstall; then
		# https://github.com/cargo-bins/cargo-binstall#installation
		curl -L --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/cargo-bins/cargo-binstall/main/install-from-binstall-release.sh | bash
	fi
	cargo binstall -y --rate-limit 10/1 --disable-strategies crate-meta-data \
			bat broot cargo-audit cargo-outdated cargo-sweep cargo-tree git-absorb git-delta \
			fd-find ripgrep
}


setup_all () {
	echo Doing everything
	setup_install_global  # so we know we have vim, git, etc.
	setup_install_local
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
[6] install (local packages)
[7] install (global packages; uses sudo)
[8] all
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
		su*|l*|6) setup_install_local; message;;
		i*|7) setup_install_global; message;;
		all|8) setup_all; exit 0;;
		*) printf "Please enter a number 0-8: ";;
	esac
done
