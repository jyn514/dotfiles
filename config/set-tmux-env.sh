#!/bin/sh
# tmux, annoyingly, does not read startup files :(
# this matters when starting a new tmux session from ssh, where no environment variables are set by default
environment=$(env -i HOME="$HOME" TERM="$TERM" PS1='; ' bash --noprofile --norc \
	-c '. /etc/profile && . ~/.profile && export PATH && printenv') || exit
while IFS='=' read -r name value; do
	case $name in
		EDITOR|VISUAL|PATH|CARGO_HOME|RUSTUP_HOME)
			tmux set-environment "$name" "$value" || exit
			;;
	esac
done << EOF
$environment
EOF
