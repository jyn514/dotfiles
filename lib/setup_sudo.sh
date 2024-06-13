#!/bin/sh

set -ex

# this script is very opinionated. you may not want to run everything here.

install_features () {
	if [ -n "$IS_DEB" ]; then
		# thanks to https://github.com/zulip/zulip/pull/10911/files
		if ! apt-cache policy | grep -q "l=Ubuntu,c=universe"; then
			add-apt-repository universe
			apt-get update
		fi
		apt-get install -y vim git build-essential cowsay figlet shellcheck  nmap \
		   python3-pip graphviz xdot xdg-utils \
		   traceroute valgrind keepassxc rclone \
		   curl jq tree pkg-config libssl-dev manpages manpages-dev bpytop git-absorb \
		   ninja-build
		if is_wsl; then
			apt install -y keychain
		fi

		# https://learn.microsoft.com/en-us/powershell/scripting/install/install-ubuntu
		if ! exists pwsh; then
			# Download the Microsoft repository GPG keys
			wget -q "https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb"
			# Register the Microsoft repository GPG keys
			dpkg -i packages-microsoft-prod.deb
			# Update the list of packages after we added packages.microsoft.com
			apt-get update
			# Install PowerShell
			apt-get install -y powershell
		fi

		if ! exists code && ! is_wsl; then
			download https://go.microsoft.com/fwlink/?LinkID=760868 code.deb
			apt install ./code.deb
		fi

		if [ "$(git --version | cut -d ' ' -f3 | cut -d. -f2)" -lt 35 ]; then
			# this often happens on WSL and borks because of zdiff3; install a newer version of git
			add-apt-repository ppa:git-core/ppa && apt update && apt install git
		fi

		if ! exists gh; then
			curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg > /usr/share/keyrings/githubcli-archive-keyring.gpg
			chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
			echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list
			apt update
			apt install gh -y
		fi
	elif [ -n "$IS_ALPINE" ]; then
		# Use GNU less so Delta works properly
		apk add less py3-pip zsh
	fi
}

install_security () {
	if ! [ -n "$IS_DEB" ]; then
		return
	fi
	apt-get update
	apt-get install -y unattended-upgrades
	unattended-upgrades || true
}

remove_unwanted () {
	if ! [ -n "$IS_DEB" ]; then
		return
	fi
	apt autoremove --purge apt-xapian-index
}

DIR="$(dirname "$(realpath "$0")")"
. "$DIR"/lib.sh
if exists dpkg; then
	IS_DEB=1
elif exists apk; then
	IS_ALPINE=1
else
	echo "$0: Unsupported distro"
	exit 1
fi

set -x
install_security
install_features
remove_unwanted
set +x
