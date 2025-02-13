#!/bin/sh
set -u

setup_basics () {
	echo Installing configuration to ~
	LOCAL="$HOME/.local/config"
	if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
	for f in "$(realpath config)"/*; do
		base=$(basename "$f")
		case $base in
    	jj.toml) DEST=$(jj config path --user || echo "$HOME/.config/jj/config.toml");;
			gitconfig) DEST="$HOME/.gitconfig";;
			git*) DEST="$HOME/.config/git/$(echo $base | sed s/^git//)";;
			*) while IFS="=" read local home; do
					if [ "$local" = "$base" ]; then
						DEST=$HOME/$home
						break
					fi
				done < config.txt
				DEST=${DEST:-$HOME/."$base"}
		esac

		if [ -L "$DEST" ]; then rm -f "$DEST"
		elif [ -e "$DEST" ]; then
				mv "$DEST" "$LOCAL"
		fi
		mkdir -p "$(dirname "$DEST")"
		ln -s "$(realpath "$f")" "$DEST"
		unset DEST
	done

	discord=$HOME/.config/discord/settings.json
	if [ -e $discord ]; then
		devtools=DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING 
		# don't have `sponge` installed yet
		jq ".$devtools = true" < $discord > tmp.json && mv tmp.json $discord
	fi

	# don't break when sourcing .bashrc
	if alias | grep -q ' ls='; then unalias ls; fi
	if [ "$HAS_REALPATH" = 0 ]; then
		grep -v 'set -.*e' < lib/realpath.sh >> ~/.local/profile
	fi
	set +ue
	. config/profile
	setup_vim # otherwise vim will error out the next time it starts up
	git clone https://github.com/tmux-plugins/tpm ~/.config/tmux/plugins/tpm
	git clone https://github.com/lincheney/fzf-tab-completion ~/.local/lib/fzf-tab-completion/
	~/.config/tmux/plugins/tpm/bin/install_plugins

	if [ ! -f ~/.local/share/zinit/zinit.git/zinit.zsh ]; then
	    printf "Installing ZDHARMA-CONTINUUM Initiative Plugin Manager (zdharma-continuum/zinit)…"
	    command mkdir -p "$HOME/.local/share/zinit" && command chmod g-rwX "$HOME/.local/share/zinit"
	    command git clone https://github.com/zdharma-continuum/zinit "$HOME/.local/share/zinit/zinit.git" && \
	        echo "Installation successful." || \
	        echo "The clone has failed."
	fi

	if exists dconf; then
		dconf load / < lib/gnome-keybindings.ini
	fi

	if exists nvim; then
		default=nvim
		# lol, the nvim desktop file has the exact same mimetype
		rg MimeType config/Helix.desktop | cut -d = -f 2 | tr \; '\n' | xargs -n1 xdg-mime default $default.desktop
		for mime in text/x-python text/x-python3 text/x-perl; do
			xdg-mime default $default.desktop $mime
		done
	fi
	if exists fx; then
		xdg-mime default fx-usercreated-1.desktop application/json
	fi
	if browser=$(xdg-settings get default-web-browser); then for mime in image/svg+xml; do
		xdg-mime default "$browser" $mime
	done
	fi

	if [ -e  ~/.config/kglobalshortcutsrc ]; then
		patch ~/.config/kglobalshortcutsrc lib/kde-keybindings.patch
		gdbus call --session --dest org.kde.KWin --object-path /KWin --method org.kde.KWin.reconfigure
	fi
unset DEST LOCAL f
}

setup_shell () {
	echo Changing default shell
	for shell in zsh fish bash; do
		if echo "$SHELL" | grep $shell; then
			echo using current shell "$shell"
			break
		elif exists $shell; then
			echo "Changing default shell to $shell"
			chsh -s "$(command -v $shell)" >/dev/null
			break
		fi
	done
unset shell
}

setup_python () {
	echo Installing python packages in python.txt
	# `pip` on MacOS is an xcode symlink that doesn't work >:(
	if exists python && python -m pip > /dev/null; then
		# may take a while
		python -m pip install --user -r python.txt
	else
		echo pip not found >&2
		return 1
	fi
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
	if ! exists nvim; then return; fi
LAZYDIR=$(nvim --cmd ":echo stdpath('data')" --cmd :q --headless --clean 2>&1)/lazy/lazy.nvim
	if ! [ -e "$LAZYDIR" ]; then
		git clone --filter=blob:none --branch=stable https://github.com/folke/lazy.nvim.git "$LAZYDIR"
	fi
unset LAZYDIR
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
		sudo --preserve-env=PATH ./lib/setup_sudo.sh
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
	if ! exists fx; then
		lib/fx-install.sh
	fi

	if ! [ -e ~/.bash-preexec.sh ]; then
		curl https://raw.githubusercontent.com/rcaloras/bash-preexec/master/bash-preexec.sh -o ~/.bash-preexec.sh
	fi
	if ! exists atuin; then
		curl --proto '=https' --tlsv1.2 -LsSf https://github.com/atuinsh/atuin/releases/latest/download/atuin-installer.sh | bash -s - --no-modify-path
		mv ~/.atuin/bin/atuin ~/.local/bin
		rm -r ~/.atuin
	fi

	# imagine an = sign: alias python=python3
	cmd_alias() {
		to=$1
		from=$2
		if ! [ -x ~/.local/bin/$to ] && exists $from; then
			ln -sf "$(command -v $from)" ~/.local/bin/$to
		fi
	}

	# On MacOS, XCode does weird shenanigans and looks at the command name >:(
	cmd_alias python python3
	cmd_alias py python3
	cmd_alias pip pip3
	cmd_alias vi nvim
	cmd_alias vim nvim

	# TODO: lol this is so funny we're literally just hardcoding the arch
	# can't just install from apt because the version is too old and doesn't support `-ln auto`
	if ! exists shfmt; then
		download https://github.com/mvdan/sh/releases/download/v3.8.0/shfmt_v3.8.0_linux_amd64 ~/.local/bin/shfmt
		chmod +x ~/.local/bin/shfmt
	fi
	if ! exists lua-language-server; then
		tar=$(download https://github.com/LuaLS/lua-language-server/releases/download/3.13.5/lua-language-server-3.13.5-linux-x64.tar.gz)
		mkdir -p ~/.local/lib/lua-lsp
		tar -C ~/.local/lib/lua-lsp -xf "$tar"
		ln -s ../lib/lua-lsp/bin/lua-language-server ~/.local/bin
	fi
	# apt package is ancient and doesn't support zsh
	if ! exists fzf; then
		tar -xOf "$(download https://github.com/junegunn/fzf/releases/download/v0.56.3/fzf-0.56.3-linux_amd64.tar.gz)" > ~/.local/bin/fzf && chmod +x ~/.local/bin/fzf
	fi

	# We use a bunch of features that are only in nvim 10.
	if ! exists nvim; then
		nvim=$(download https://github.com/neovim/neovim/releases/download/v0.10.4/nvim-linux-x86_64.tar.gz)
		libdir=$HOME/.local/lib
		mkdir -p "$libdir"
		tar -C "$libdir" -xf "$nvim"
		ln -s "$libdir"/nvim-linux-x86_64/bin/nvim ~/.local/bin/nvim
	fi

	if ! [ -d ~/.local/lib/PowerShellEditorServices ]; then
		mkdir -p ~/.local/lib/PowerShellEditorServices
		pslsp=$(download https://github.com/PowerShell/PowerShellEditorServices/releases/download/v4.2.0/PowerShellEditorServices.zip)
		unzip "$pslsp" -d ~/.local/lib/PowerShellEditorServices
	fi

	#npm install -g perlnavigator-server bash-language-server
}

install_rust() {
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
	cd "$OLDPWD"
	# avoid recompiling so much
	export CARGO_TARGET_DIR=/tmp/cargo
	mkdir -p $CARGO_TARGET_DIR
	# set GITHUB_TOKEN if possible so this doesn't hit a rate limit
	# to manually set a token see https://github.com/settings/tokens
	if exists gh; then
    	export GITHUB_TOKEN=$(gh auth token)
	fi
	# we need to check for the full path because we have a wrapper in dotfiles/bin
	if ! [ -x "${CARGO_HOME:-~/.cargo}/bin/cargo-binstall" ]; then
		# https://github.com/cargo-bins/cargo-binstall#installation
		curl -L --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/cargo-bins/cargo-binstall/main/install-from-binstall-release.sh | bash
	else
		# update to latest version; old versions often hit a rate limit
		cargo binstall cargo-binstall
	fi
	tr -d '\r' <rust.txt | xargs cargo binstall -y --rate-limit 10/1 --disable-strategies compile --continue-on-failure

	# extensions are managed by vscode itself
}

setup_all () {
	echo Doing everything
	setup_install_global  # so we know we have vim, git, etc.
	setup_install_local
	setup_basics
	setup_shell
	setup_python
	setup_vim
	# this is a mess rn
	# setup_backup
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

run() {
	case "$1" in
		q*|e*|0) exit 0;;
		dot*|bas*|1) setup_basics;;
		sh*|2) setup_shell;;
		py*|3) setup_python;;
		vi*|4) setup_vim;;
		bac*|5) setup_basics; setup_backup;;
		su*|l*|6) setup_install_local;;
		i*|g*|7) setup_install_global;;
		all|8) setup_all; exit 0;;
		*) return 1;;
	esac
}

if ! [ $# = 0 ]; then
	if ! run "$1"; then message; fi
else
    message
    while read -r choice; do
    	if ! run "$choice"; then
				echo "Please enter a number 0-8: "
			fi
    	message
    done
fi
