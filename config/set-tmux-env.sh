#!/bin/sh
# tmux, annoyingly, does not read startup files :(
# this matters when starting a new tmux session from ssh, where no environment variables are set by default
tmux_command=$(command -v tmux) || exit
set -- env -i HOME="$HOME" TERM="$TERM" PS1='; ' TMUX_COMMAND="$tmux_command"
if [ "${TMUX+x}" ]; then
	set -- "$@" TMUX="$TMUX"
fi
if [ "${TMUX_TMPDIR+x}" ]; then
	set -- "$@" TMUX_TMPDIR="$TMUX_TMPDIR"
fi
# shellcheck disable=SC2016  # The inner Bash expands these variables.
exec "$@" bash --noprofile --norc -c '
		. /etc/profile && . ~/.profile || exit
		for name in EDITOR VISUAL PATH CARGO_HOME RUSTUP_HOME; do
			if [[ -v $name ]]; then
				"$TMUX_COMMAND" set-environment "$name" "${!name}" || exit
			fi
		done
	'
