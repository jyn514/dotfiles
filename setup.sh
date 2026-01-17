#!/bin/sh
set -u

libdir=$HOME/.local/lib

if [ "$(uname -s)" = Darwin ]; then
	IS_MACOS=1
fi

install_alpine() {
	install_clojure
}

install_brew() {
	# note that we don't actually pass sudo here
	./lib/setup_sudo.sh install_features
	ln -fs $(brew --prefix)/opt/antidote/share/antidote ~/.config/zsh/antidote
	cmd_alias gdu gdu-go
	if exists cargo; then
		cargo install --git https://github.com/jyn514/brew-command-not-found --branch new-year-new-brew --locked
	fi
}

install_linux_lol() {
	mkdir -p $libdir

	cpp=$libdir/cpptools
	# TODO: don't hard-code an arch lmao
	if ! [ -d $cpp ]; then
		vsix=$(download https://github.com/microsoft/vscode-cpptools/releases/latest/download/cpptools-linux-x64.vsix)
		unzip "$vsix" -d $cpp
		chmod +x $cpp/extension/debugAdapters/bin/OpenDebugAD7
	fi

	if [ "$(uname)" = Linux ] && ! exists glide; then
		set -x
		glide=$(download "https://github.com/glide-browser/glide/releases/latest/download/glide.linux-$(uname -m).tar.xz")
		tar -C $libdir -xf "$glide"
		ln -sf $libdir/glide/glide-bin ~/.local/bin/glide
		set +x
		exit 1
	fi

	install_clojure
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
		if ! exists rustup-init; then
			rustup_init=/tmp/rustup-init.sh
			curl https://sh.rustup.rs/ > $rustup_init
			chmod +x $rustup_init
		else
			rustup_init=rustup-init
		fi
		$rustup_init -y --profile minimal -c rustfmt -c clippy -c rust-analyzer
		if [ "${OSTYPE:-}" = msys ]; then
			PATH="$PATH:${CARGO_HOME:-$HOME/.cargo}/bin"
		else
			. "${CARGO_HOME:-$HOME/.cargo}/env"
		fi
		rustup toolchain add nightly --profile minimal -c clippy -c miri
		rustup default nightly
		unset rustup_init t
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
	tr -d '\r' < install/rust.txt | xargs cargo binstall --quiet --no-confirm --rate-limit 10/1 --disable-strategies compile --continue-on-failure
	if exists bat; then
		bat cache --build
	fi

	# extensions are managed by vscode itself
}

install_clojure() {
	if ! exists clojure; then
		install=$(download https://github.com/clojure/brew-install/releases/latest/download/linux-install.sh)
		bash "$install" --prefix ~/.local/lib/clojure
		ln -s ~/.local/lib/clojure/bin/clojure ~/.local/bin/
		rm "$install"
	fi
}

# create_macos_app() {
# 	cli=$1
# 	domain=dev.jyn.$cli
# 	pb=/usr/libexec/PlistBuddy
# 	app=${cli}.app
# 	app_plist=$app/Contents/Info.plist
# 	workflow_plist="$app/Contents/Resources/document.wflow/Contents.plist"
#
# 	mkdir -p ~/Applications
# 	(
# 		cd ~/Applications
# 		mkdir -p $app/Contents/MacOS $app/Contents/Resources $(dirname $workflow_plist)
# 		# note: hard link
# 		if [ $cli = nvim ]; then
# 			p=$(which hx-hax)
# 			n=hx-hax
# 		else
# 			p=$(which $cli)
# 			n=$cli
# 		fi
# 		$pb -c "add CFBundleDisplayName string $cli" $app_plist
# 		$pb -c "add CFBundleExecutable string Application Stub" $app_plist
# 		$pb -c "add CFBundleIdentifier string $domain" $app_plist
# 		$pb -c "add CFBundlePackageType string APPL" $app_plist
# 		$pb -c "add CFBundleDocumentTypes array" $app_plist
# 		$pb -c "add CFBundleDocumentTypes:0 dict" $app_plist
# 		$pb -c "add CFBundleDocumentTypes:0:CFBundleTypeRole string Editor" $app_plist
# 		$pb -c "add CFBundleDocumentTypes:0:LSItemContentTypes array" $app_plist
# 		$pb -c "add CFBundleDocumentTypes:0:LSItemContentTypes:0 string public.data" $app_plist
# 		# $pb -c "add NSPrincipalClass string NSApplication" $plist
# 		# /System/Library/Frameworks/CoreServices.framework/Versions/Current/Frameworks/LaunchServices.framework/Versions/Current/Support/lsregister -f $app
# 	
# 		cp -r "/System/Library/CoreServices/Automator Application Stub.app/Contents/" "$app/"
# 		# $pb -c "Clear dict" "$workflow_plist" 2>/dev/null || true
# 		$pb -c "Add :AMApplicationBuild string 2.10" "$workflow_plist"
# 		$pb -c "Add :AMApplicationVersion string 2.10" "$workflow_plist"
# 		$pb -c "Add :actions array" "$workflow_plist"
# 		$pb -c "Add :actions:0 dict" "$workflow_plist"
# 		$pb -c "Add :actions:0:action string com.apple.coreservices.RunShellScript" "$workflow_plist"
# 		$pb -c "Add :actions:0:parameters dict" "$workflow_plist"
# 		$pb -c 'Add :actions:0:parameters:COMMAND_STRING string '$cli'"$@"' "$workflow_plist"
# 		$pb -c "Add :actions:0:parameters:shell string /bin/bash" "$workflow_plist"
# 		$pb -c "Add :actions:0:parameters:inputMethod integer 0" "$workflow_plist"
# 	)
# }

register_editor() {
	cli=$1
	mime=$2
	if exists xdg-mime; then
		xdg-mime default $cli.desktop $mime
	elif exists duti; then
		kind=${3:-editor}
		id=com.apple.automator.$cli;

		duti -s $id $mime $kind

		case $mime in
			*/plain) ext=txt;;
			*-python*) ext=py;;
			*-perl*) ext=perl;;
			*-javascript*) ext=js;;
			*-csh*) ext=csh;;
			*-c++*) ext=cpp;;
			*-chdr) ext=h;;
			*-csrc|*-c) ext=c;;
			*-java) ext=java;;
			*/json) ext=json;;
			*/markdown) ext=md;;
			*) return;;
		esac
		set -x
		duti -s $id .${ext} $kind
		set +x
	fi
}

setup_mimetypes() {
	if exists nvim; then
		if [ -n "${IS_MACOS:-}" ]; then
			if [ -d /Applications/nvim.app ]; then
				defaults write com.apple.LaunchServices/com.apple.launchservices.secure LSHandlers -array-add '{LSHandlerContentType=public.plain-text;LSHandlerRoleAll=com.apple.automator.nvim;}'
				echo "To see updated mimetype handlers, you must restart you MacBook" >&2
			else
				echo "To setup nvim file associations, you need to create a Application using Automator."
				echo "Go to File -> New -> Application -> Run Shell Script -> Pass input -> as arguments."
				echo "Then, copy paste this script:"
				echo
echo 'for f in "$@"
do
	hx-hax "$f"
done'
				echo
				echo "Finally, go to File -> Save -> Save as 'nvim' -> Where 'Applications'."
				echo 'Do the same for fx with the script: fx "$@"'
				exit 1
			fi
		fi

		# lol, the nvim desktop file has the exact same mimetype
		for mime in $(grep MimeType config/Helix.desktop | cut -d = -f 2 | tr \; '\n'); do
			register_editor nvim "$mime"
		done
		for mime in text/markdown text/x-python text/x-python3 text/x-perl application/javascript application/x-csh; do
			register_editor nvim $mime
		done
	fi

	if [ -n "${IS_MACOS:-}" ]; then
		for ext in rs; do
			duti -s com.apple.automator.nvim .${ext} editor
		done
	elif exists fx; then
		register_editor fx application/json viewer
	fi

	if exists xdg-settings && browser=$(xdg-settings get default-web-browser); then
		for mime in image/svg+xml; do
			register_editor "$browser" $mime viewer
		done
	fi
}

setup_basics () {
	echo Installing configuration to ~
	LOCAL="$HOME/.local/config"
	if ! [ -d "$LOCAL" ]; then mkdir -p "$LOCAL"; fi
	for f in "$(realpath config)"/*; do
		base=$(basename "$f")
		case $base in
    	jj.toml) DEST=$(jj config path --user || echo "$HOME/.config/jj/config.toml");;
			git*) DEST="$HOME/.config/git/$(echo $base | sed s/^git//)";;
			*) while IFS="=" read local home; do
					if [ "$local" = "$base" ]; then
						DEST=$HOME/$home
						break
					fi
				done < install/config.txt
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

	# otherwise git defaults to ~/.git-credentials: https://git-scm.com/docs/git-credential-store#FILES
	touch ~/.config/git/credentials
	mkdir -p ~/.local/state/zsh

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
	if ! [ -d ~/.config/tmux/plugins/tpm ]; then
		git clone https://github.com/tmux-plugins/tpm ~/.config/tmux/plugins/tpm
	fi
	if ! [ -d "$libdir"/fzf-tab-completion ]; then
		git clone https://github.com/lincheney/fzf-tab-completion "$libdir"/fzf-tab-completion/
	fi
	~/.config/tmux/plugins/tpm/bin/install_plugins

	if exists dconf; then
		dconf load / < lib/gnome-keybindings.ini
	fi

	if exists bat; then
		mkdir -p "$(bat --config-dir)/syntaxes"
		(
			cd "$(bat --config-dir)/syntaxes"
			# TODO: just inline this into my dotfiles
			if ! [ -e mumps.sublime-syntax ]; then
				download https://github.com/ksherlock/MUMPS.tmbundle/raw/refs/heads/master/Syntaxes/mumps.sublime-syntax mumps.sublime-syntax
				sed -i 's/^file_extensions:.*/file_extensions: [m]/' mumps.sublime-syntax
			fi
		)
		bat cache --build >/dev/null
	fi

	if exists atuin; then
		mkdir -p ~/.config/fish/completions
		atuin gen-completions --shell fish > ~/.config/fish/completions/atuin.fish
	fi

	if [ -e  ~/.config/kglobalshortcutsrc ]; then
		setup_kde
	fi

	setup_mimetypes
unset DEST LOCAL f
}

setup_kde() {
	if ! [ -d ~/.local/share/kwin/scripts/krohnkite ]; then
		krohnkite=$(download https://codeberg.org/anametologin/Krohnkite/releases/download/latest/krohnkite.kwinscript)
		kpackagetool6 -t KWin/Script -i "$krohnkite"
	fi

	if ! [ -d $libdir/dynamic_workspaces ]; then
		git clone https://github.com/maurges/dynamic_workspaces "$libdir"/dynamic_workspaces
		kpackagetool6 -t KWin/Script -i "$libdir"/dynamic_workspaces
	fi

	patch ~/.config/kglobalshortcutsrc lib/kde-keybindings.patch
	gdbus call --session --dest org.kde.KWin --object-path /KWin --method org.kde.KWin.reconfigure
}

setup_shell () {
	echo Changing default shell
	for shell in fish zsh bash; do
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
		# lmao why does `--user` think it breaks system packages
		python -m pip install --quiet --user --break-system-packages -r install/python.txt
	else
		echo pip not found >&2
		return 1
	fi
}

setup_vim () {
	echo Installing vim plugins
VIMDIR="$HOME/.vim/autoload"
	if exists vim && ! [ -e "$VIMDIR/plug.vim" ]; then
		mkdir -p "$VIMDIR"
		download https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim "$VIMDIR/plug.vim"
		vim -c PlugInstall -c q -c q
	fi
unset VIMDIR
	if exists nvim; then
LAZYDIR=$(nvim --cmd ":echo stdpath('data')" --cmd :q --headless --clean 2>&1)/lazy/lazy.nvim
		if ! [ -e "$LAZYDIR" ]; then
			git clone --filter=blob:none --branch=stable https://github.com/folke/lazy.nvim.git "$LAZYDIR"
			nvim --headless +:q
		fi
unset LAZYDIR
	fi
	if ! exists nvim && ! exists vim; then
		echo "no vim installed ..."
		return 1
	fi
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
		sudo --preserve-env=PATH ./lib/setup_sudo.sh main
	elif exists doas; then
		doas ./lib/setup_sudo.sh main
	elif exists su; then
		su root -c ./lib/setup_sudo.sh main
	else
		./lib/setup_sudo.sh main
	fi
}

# setup_macos() {
# 	brew install -q duti
# 	if exists nvim; then
# 		create_macos_app nvim io.neovim
# 	fi
# 	if exists fx; then
# 		create_macos_app fx wtf.fx
# 	fi
# }

setup_install_local () {
	echo Installing user packages
	mkdir -p ~/.local/bin

	if exists apk; then
		install_alpine
	elif [ "$(uname)" = Linux ] && [ "$(uname -m)" = x86_64 ]; then
		install_linux_lol
	elif exists brew; then
		install_brew
	fi

	if [ -n "${IS_MACOS:-}" ]; then
		:
		# 	setup_macos
	fi

	if exists pacman && ! exists 1password; then
		curl -sS https://downloads.1password.com/linux/keys/1password.asc | gpg --import
		git clone https://aur.archlinux.org/1password.git $libdir/1password
		(cd $libdir/1password && makepkg -si)
	fi

	if ! [ -e ~/.config/zsh/antidote ]; then
		git clone --depth=1 https://github.com/mattmc3/antidote.git ~/.config/zsh/antidote
	fi
	if ! [ -e ~/.config/fish/fish_plugins ]; then
		curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish | fish -c 'source && fisher install jorgebucaran/fisher'
		fish -c 'fisher install (command cat install/fish.txt)'
	fi
	# node just doesn't run on musl hosts, lol
	if ! [ -d ~/.local/share/nvm/v* ] && ! exists apk; then
		# fish's nvm is *much* faster than the original
		fish -c '\
		nvm install lts
		nvm use lts
		npm install -g --no-fund --silent pnpm perlnavigator-server bash-language-server typescript-language-server oxlint vscode-langservers-extracted
		echo "add_path ~/.local/share/nvm/$(nvm current)/bin" >> ~/.local/profile'
	fi

	# On MacOS, XCode does weird shenanigans and looks at the command name >:(
	cmd_alias python python3
	cmd_alias py python3
	cmd_alias pip pip3
	cmd_alias vi nvim
	cmd_alias vim nvim

	if ! [ -d $libdir/PowerShellEditorServices ]; then
		mkdir -p $libdir/PowerShellEditorServices
		pslsp=$(download https://github.com/PowerShell/PowerShellEditorServices/releases/download/v4.2.0/PowerShellEditorServices.zip)
		unzip -q "$pslsp" -d $libdir/PowerShellEditorServices
	fi

	# needs a password for cargo-binstall to log into github
	install_rust
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
	printf "%s" "[q|0] exit
[dot|1] dotfiles
[sh|2] shell
[py|3] python
[vi|4] vim
[backup|5] backup
[local|6] install (local packages)
[sudo|7] install (global packages; uses sudo)
[kde|8] kde
[all|9] all
Choose setup to run: "
}

# main

cd "$(dirname "$0")"
. lib/lib.sh

run() {
	case "$1" in
		q*|e*|0) exit 0;;
		dot*|bas*|1) setup_basics;;
		sh*|2) setup_shell;;
		py*|3) setup_python;;
		vi*|4) setup_basics; setup_vim;;
		bac*|5) setup_basics; setup_backup;;
		l*|6) setup_install_local; setup_python;;
		sudo*|i*|g*|7) setup_install_global;;
		kde*|8) setup_kde;;
		all|9) setup_all;;
		macos|10) setup_macos;;
		*) return 126;;
	esac
}

if ! [ $# = 0 ]; then
	run "$1"
	if [ $? = 126 ]; then message; fi
else
	message
	while read -r choice; do
		if ! run "$choice"; then
			echo "Please enter a number 0-8: "
		fi
		message
	done
fi
