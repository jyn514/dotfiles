#!/bin/sh
set -u

libdir=$HOME/.local/lib

if [ "$(uname -s)" = Darwin ]; then
	IS_MACOS=1
fi

install_macos_local() {
	# note that we don't actually pass sudo here
	./lib/setup_sudo.sh install_features
	brew install -q duti
	ln -fs $(brew --prefix)/opt/antidote/share/antidote ~/.config/zsh/antidote
	cmd_alias gdu gdu-go
	if exists cargo; then
		brew_revision=$(mise_exec python lib/install_bootstrap.py get git brew-command-not-found revision)
		cargo install --git https://github.com/jyn514/brew-command-not-found \
			--rev "$brew_revision" --locked
		unset brew_revision
	fi
}

mise_exec() {
	MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise exec -- "$@" < /dev/null
}

install_platform_bundles() {
	if exists apk; then
		python3 lib/install_platform_bundles.py cpptools powershell-editor-services
	else
		mise_exec python lib/install_platform_bundles.py cpptools powershell-editor-services
	fi
}

authenticate_mise_github() {
	MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise token github --oauth
}

warn_mise_github_auth_skipped() {
	echo "GitHub authentication skipped ($1); mise may hit the anonymous API rate limit" >&2
}

offer_mise_github_oauth() {
	github_auth=$(MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise token github 2>/dev/null || true)
	case $github_auth in
		''|*'(none)'*) ;;
		*) unset github_auth; return 0;;
	esac
	unset github_auth
	if [ -t 0 ] && [ -r /dev/tty ]; then
		printf 'Authenticate mise with GitHub to avoid API rate limits? [y/N] ' > /dev/tty
		read -r authenticate_github < /dev/tty || return 0
	else
		if [ -z "${SETUP_INTERACTIVE:-}" ]; then
			warn_mise_github_auth_skipped "setup is noninteractive"
			return 0
		fi
		printf 'Authenticate mise with GitHub to avoid API rate limits? [y/N] '
		if ! read -r authenticate_github; then
			warn_mise_github_auth_skipped "no response was available on stdin"
			return 0
		fi
	fi
	case $authenticate_github in
		y|Y|yes|YES)
			if [ -t 0 ] && [ -r /dev/tty ]; then
				authenticate_mise_github < /dev/tty > /dev/tty || {
					warn_mise_github_auth_skipped "OAuth login failed"
					return
				}
			else
				authenticate_mise_github || {
					warn_mise_github_auth_skipped "OAuth login failed"
					return
				}
			fi
			;;
		*) warn_mise_github_auth_skipped "declined by user";;
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
	if exists apk; then
		# Alpine supplies these itself, or has no compatible prebuilt release.
		env MISE_DISABLE_TOOLS='node,python,npm:pnpm,npm:perlnavigator-server,npm:bash-language-server,npm:typescript-language-server,npm:oxlint,npm:vscode-langservers-extracted,aqua:Wilfred/difftastic' \
			MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise install --yes < /dev/null || return
	else
		MISE_GLOBAL_CONFIG_FILE="$MISE_SETUP_CONFIG" mise install --yes < /dev/null || return
	fi
}

setup_mimetypes() {
	echo "Registering mimetypes"
	python3 lib/setup_mimetypes.py
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
		python3 lib/install_bootstrap.py clone tpm ~/.config/tmux/plugins/tpm
	fi
	if ! [ -d "$libdir"/fzf-tab-completion ]; then
		python3 lib/install_bootstrap.py clone fzf-tab-completion "$libdir"/fzf-tab-completion
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
		ln -fs "$PWD/config/bat/mumps.sublime-syntax" \
			"$(bat --config-dir)/syntaxes/mumps.sublime-syntax"
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
		krohnkite=$(tmp_file krohnkite.XXXXXX)
		python3 lib/install_bootstrap.py download krohnkite "$krohnkite" || return
		kpackagetool6 -t KWin/Script -i "$krohnkite"
		rm -f "$krohnkite"
	fi

	if ! [ -d $libdir/dynamic_workspaces ]; then
		python3 lib/install_bootstrap.py clone dynamic-workspaces "$libdir"/dynamic_workspaces
		kpackagetool6 -t KWin/Script -i "$libdir"/dynamic_workspaces
	fi

	if ! patch --forward --silent ~/.config/kglobalshortcutsrc lib/kde-keybindings.patch; then
		patch --reverse --dry-run --silent ~/.config/kglobalshortcutsrc \
			lib/kde-keybindings.patch >/dev/null 2>&1 || return
	fi
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
		python3 lib/install_bootstrap.py download vim-plug "$VIMDIR/plug.vim"
		vim -c PlugInstall -c q -c q
	fi
unset VIMDIR
	if exists nvim; then
LAZYDIR=$(nvim --cmd ":echo stdpath('data')" --cmd :q --headless --clean 2>&1)/lazy/lazy.nvim
		if ! [ -e "$LAZYDIR" ]; then
			python3 lib/install_bootstrap.py clone lazy.nvim "$LAZYDIR"
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
	cron_entry="0 12 * * * $BACKUP_COMMAND"
	if ! grep -Fqx "$cron_entry" "$TMP_FILE"; then
		echo "$cron_entry" >> "$TMP_FILE"
	fi
	crontab "$TMP_FILE"
	rm -f "$TMP_FILE"
	unset BACKUP_COMMAND TMP_FILE cron_entry
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

setup_install_local () {
	echo Installing user packages
	if exists apk && ! [ -e /usr/lib/libgcc_s.so.1 ]; then
		echo "Alpine's libgcc package is required for Rust; run setup option 7 or 9 first" >&2
		return 1
	fi
	mkdir -p ~/.local/bin
	install_mise || return
	install_platform_bundles || return

	if [ -n "${IS_MACOS:-}" ]; then
		install_macos_local || return
	fi

	if exists pacman && ! exists 1password; then
		./lib/install_1password_arch.sh || return
	fi

	if ! [ -e ~/.config/zsh/antidote ]; then
		mise_exec python lib/install_bootstrap.py clone antidote ~/.config/zsh/antidote
	fi
	if ! [ -e ~/.config/fish/fish_plugins ]; then
		fisher_installer=$(tmp_file fisher.XXXXXX)
		mise_exec python lib/install_bootstrap.py download fisher "$fisher_installer" || return
		fisher_revision=$(mise_exec python lib/install_bootstrap.py get git fisher revision)
		fish -c 'source $argv[1]; fisher install jorgebucaran/fisher@$argv[2]' \
			"$fisher_installer" "$fisher_revision"
		rm -f "$fisher_installer"
		zoxide_revision=$(mise_exec python lib/install_bootstrap.py get git zoxide.fish revision)
		fish -c 'fisher install icezyclon/zoxide.fish@$argv[1]' "$zoxide_revision"
		unset fisher_installer fisher_revision zoxide_revision
	fi
	# On MacOS, XCode does weird shenanigans and looks at the command name >:(
	cmd_alias python python3
	cmd_alias py python3
	cmd_alias pip pip3
	cmd_alias vi nvim
	cmd_alias vim nvim

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

MISE_SETUP_CONFIG=$PWD/config/mise.toml
export MISE_SETUP_CONFIG

run() {
	case "$1" in
		q*|e*|0) exit 0;;
		dot*|1) setup_dotfiles;;
		install-global) setup_install_global_packages;;
		install-local) setup_install_local && setup_python;;
		bas*) setup_basics;;
		mime*) setup_mimetypes;;
		sh*|2) setup_shell;;
		py*|3) setup_python;;
		vi*|4) setup_vim;;
		bac*|5) setup_backup;;
		l*|6) setup_install_local && setup_python;;
		sudo*|i*|g*|7) setup_install_global;;
		kde*|8) setup_kde;;
		all|9) setup_all;;
		*) return 126;;
	esac
}

if ! [ $# = 0 ]; then
	case "$1" in
		all|9|install-local|l*|6)
			if [ -z "${CI:-}" ] && [ -z "${SETUP_NONINTERACTIVE:-}" ]; then
				SETUP_INTERACTIVE=1
			fi
			;;
	esac
	run "$1"
	status=$?
	if [ "$status" = 126 ]; then message; fi
	exit "$status"
else
	SETUP_INTERACTIVE=1
	message
	while read -r choice; do
		if ! run "$choice"; then
			echo "Please enter a number 0-9: "
		fi
		message
	done
fi
