#!/bin/sh
set -eu

# A clean Bash login environment remains the source of truth.
tmux_command=$(command -v tmux) || exit

set -- env -i HOME="$HOME" TERM="$TERM" PS1='; '
if [ "${TMUX+x}" ]; then
	set -- "$@" TMUX="$TMUX"
fi
if [ "${TMUX_TMPDIR+x}" ]; then
	set -- "$@" TMUX_TMPDIR="$TMUX_TMPDIR"
fi

# shellcheck disable=SC2016  # The inner Bash expands these variables.
exec "$@" bash --noprofile --norc -c '
	. /etc/profile && . ~/.profile || exit
	set -u
	tmux=$1
	set_one() {
		if [ "$2" ]; then
			"$tmux" set-environment "$1" "$3"
		else
			"$tmux" set-environment -u "$1"
		fi
	}
	set_one EDITOR "${EDITOR+x}" "${EDITOR-}" || exit
	set_one VISUAL "${VISUAL+x}" "${VISUAL-}" || exit
	set_one PATH "${PATH+x}" "${PATH-}" || exit
	set_one CARGO_HOME "${CARGO_HOME+x}" "${CARGO_HOME-}" || exit
	set_one RUSTUP_HOME "${RUSTUP_HOME+x}" "${RUSTUP_HOME-}"
' set-tmux-env "$tmux_command"
