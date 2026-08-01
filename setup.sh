#!/bin/sh
set -u

libdir=$HOME/.local/lib

if [ "$(uname -s)" = Darwin ]; then
	IS_MACOS=1
fi

install_macos_local() {
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

}

mise_exec() {
	MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise exec -- "$@" < /dev/null
}

authenticate_mise_github() {
	if [ -n "${MISE_GITHUB_OAUTH_CLIENT_ID:-}" ]; then
		mise token github --oauth
	elif exists gh; then
		gh auth login --hostname github.com --git-protocol https --web
	else
		echo "GitHub authentication requires gh or MISE_GITHUB_OAUTH_CLIENT_ID" >&2
		return 1
	fi
}

offer_mise_github_oauth() {
	[ -t 0 ] && [ -r /dev/tty ] || return 0
	mise token github 2>/dev/null | grep -qv '(none)' && return 0
	exists gh || [ -n "${MISE_GITHUB_OAUTH_CLIENT_ID:-}" ] || return 0
	printf 'Authenticate mise with GitHub to avoid API rate limits? [y/N] ' > /dev/tty
	read -r authenticate_github < /dev/tty || return 0
	case $authenticate_github in
		y|Y|yes|YES) authenticate_mise_github < /dev/tty > /dev/tty || return;;
	esac
}

install_mise() {
	if ! exists mise; then
		mise_installer=$(tmp_file mise-installer.XXXXXX)
		download https://mise.run "$mise_installer" || {
			rm -f "$mise_installer"
			return 1
		}
		sh "$mise_installer" || {
			rm -f "$mise_installer"
			return 1
		}
		rm -f "$mise_installer"
		unset mise_installer
		PATH="$HOME/.local/bin:$PATH"
		exists mise || {
			echo "mise installer completed without installing mise" >&2
			return 1
		}
	fi
	offer_mise_github_oauth || return
	MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise install --yes < /dev/null || return
	# These crates do not publish binaries that mise can install on every supported
	# platform. Preserve the no-compilation policy and explicitly omit them there.
	case $(uname -m) in
		aarch64|arm64) cargo_tools=$(sed '/^librespot$/d' install/rust.txt);;
		*) cargo_tools=$(cat install/rust.txt);;
	esac
	printf '%s\n' "$cargo_tools" | tr -d '\r' | xargs env MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise exec -- cargo binstall --quiet --no-confirm --rate-limit 10/1 --disable-strategies compile --continue-on-failure || return
	unset cargo_tools
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
	echo "Registering mimetypes"
	if exists nvim; then
		if [ -n "${IS_MACOS:-}" ]; then
			if [ -d /Applications/nvim.app ]; then
				defaults write com.apple.LaunchServices/com.apple.launchservices.secure LSHandlers -array-add '{LSHandlerContentType=public.plain-text;LSHandlerRoleAll=com.apple.automator.nvim;}'
				echo "To see updated mimetype handlers, you must restart your MacBook" >&2
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

setup_dotfiles () {
	echo Installing configuration to ~
	if ! exists python3; then
		echo "dotfile setup requires python3; run setup option 7 or 9 first" >&2
		return 1
	fi
	JJ_CONFIG_PATH=$(jj config path --user 2>/dev/null || echo "$HOME/.config/jj/config.toml")
	export JJ_CONFIG_PATH
	python3 lib/backup_dotfile_collisions.py install.conf.json || return
	lib/dotbot/bin/dotbot --quiet -d "$(pwd)" -c install.conf.json || return

	# otherwise git defaults to ~/.git-credentials: https://git-scm.com/docs/git-credential-store#FILES
	touch ~/.config/git/credentials
	unset JJ_CONFIG_PATH
}

setup_basics () {
	setup_dotfiles || return

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

	if exists batcat; then
		cmd_alias bat batcat
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
		if echo "${SHELL:-}" | grep $shell; then
			echo using current shell "$shell"
			break
		elif exists $shell; then
			echo "Changing default shell to $shell"
			if ! exists chsh; then
				echo "chsh is required to change shells; run setup option 7 or 9 first" >&2
				return 1
			fi
			chsh -s "$(command -v $shell)" >/dev/null
			break
		fi
	done
unset shell
}

setup_python () {
	echo Installing python packages in python.txt
	if exists apk; then
		python3 -m pip install --quiet --break-system-packages -r install/python.txt
	else
		mise_exec python -m pip install --quiet -r install/python.txt
	fi
}

prepare_vim_setup () {
	if ! exists nvim && ! exists vim; then
		echo "no vim installed ..."
		return 1
	fi
}

setup_vim () {
	echo Installing vim plugins
	prepare_vim_setup || return
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
}

prepare_backup_setup () {
	BACKUP_COMMAND=$(realpath bin/backup)
	if ! [ -x "$BACKUP_COMMAND" ]; then
		echo "backup command not found: $BACKUP_COMMAND" >&2
		return 1
	fi
	if ! exists crontab; then
		echo "backup setup requires crontab" >&2
		return 1
	fi
}

setup_backup () {
	echo Setting up daily backup
	prepare_backup_setup || return
	TMP_FILE=$(tmp_file cronjob.XXXXXX)
	# tried piping this straight to `crontab -`
	# it failed when non-interactive for some reason
	crontab -l > "$TMP_FILE" 2>/dev/null || true;  # ignore missing crontab
	echo "0 12 * * * $BACKUP_COMMAND" >> "$TMP_FILE" && crontab "$TMP_FILE"
	rm -f "$TMP_FILE"
	unset BACKUP_COMMAND TMP_FILE
}

setup_install_global () {
	echo Installing global packages
	if [ "$(id -u)" = 0 ]; then
		./lib/setup_sudo.sh main
	elif exists sudo; then
		sudo --preserve-env=PATH ./lib/setup_sudo.sh main
	elif exists doas; then
		doas ./lib/setup_sudo.sh main
	elif exists su; then
		su root -c './lib/setup_sudo.sh main'
	else
		./lib/setup_sudo.sh main
	fi
}

setup_install_global_packages () {
	echo Installing global packages
	if [ "$(id -u)" = 0 ]; then
		./lib/setup_sudo.sh install_features
	elif exists sudo; then
		sudo --preserve-env=PATH ./lib/setup_sudo.sh install_features
	elif exists doas; then
		doas ./lib/setup_sudo.sh install_features
	else
		echo "install-global requires root, sudo, or doas" >&2
		return 1
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
	if exists apk && ! [ -e /usr/lib/libgcc_s.so.1 ]; then
		echo "Alpine's libgcc package is required for Rust; run setup option 7 or 9 first" >&2
		return 1
	fi
	mkdir -p ~/.local/bin
	install_mise || return

	if ! exists apk && [ "$(uname)" = Linux ] && [ "$(uname -m)" = x86_64 ]; then
		install_linux_lol || return
	elif [ -n "${IS_MACOS:-}" ]; then
		install_macos_local || return
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
	if exists bat; then
		bat cache --build
	fi

}

setup_all () {
	echo Doing everything
	setup_install_global || return  # so we know we have vim, git, etc.
	setup_install_local || return
	setup_basics || return
	setup_shell || return
	setup_python || return
	setup_vim || return
	# this is a mess rn
	# setup_backup
	return 0
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
. lib/env.sh

MISE_SETUP_DIR=$(tmp_dir mise-config.XXXXXX)
MISE_SETUP_CONFIG=$MISE_SETUP_DIR/config.toml
sed '/^"cargo:/d' config/mise.toml > "$MISE_SETUP_CONFIG"
cp config/mise.lock "$MISE_SETUP_DIR/mise.lock"
if exists apk; then
	# Preserve the old Alpine behavior: use packaged Python and difftastic, and
	# skip Node because it has no musl release and would compile from source.
	sed '/^node = /d; /^python = /d; /^"npm:/d; /^"aqua:Wilfred\/difftastic"/d; s/depends = \["python", "uv"\]/depends = ["uv"]/' "$MISE_SETUP_CONFIG" > "$MISE_SETUP_CONFIG.alpine"
	mv "$MISE_SETUP_CONFIG.alpine" "$MISE_SETUP_CONFIG"
fi
trap 'rm -rf "$MISE_SETUP_DIR"' EXIT HUP INT TERM
export MISE_SETUP_CONFIG

run() {
	case "$1" in
		q*|e*|0) exit 0;;
		dot*|1) setup_dotfiles;;
		install-global) setup_install_global_packages;;
		install-local) setup_install_local && setup_python;;
		bas*) setup_basics;;
		sh*|2) setup_shell;;
		py*|3) setup_python;;
		vi*|4) setup_vim;;
		bac*|5) setup_backup;;
		l*|6) setup_install_local && setup_python;;
		sudo*|i*|g*|7) setup_install_global;;
		kde*|8) setup_kde;;
		all|9) setup_all;;
		macos|10) setup_macos;;
		*) return 126;;
	esac
}

if ! [ $# = 0 ]; then
	run "$1"
	status=$?
	if [ "$status" = 126 ]; then message; fi
	exit "$status"
else
	message
	while read -r choice; do
		if ! run "$choice"; then
			echo "Please enter a number 0-8: "
		fi
		message
	done
fi
