#!/bin/sh
set -eu

# A clean Bash login environment remains the source of truth. Once the startup
# files have run, hand the inherited environment to the Python tmux receiver.
tmux_command=$(command -v tmux) || exit
python_command=$(command -v python3) || exit
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit
receiver=$script_dir/set-environment
if ! [ -x "$receiver" ]; then
	receiver=$script_dir/../tools/tmux-admin/set-environment
fi
if ! [ -x "$receiver" ]; then
	echo "tmux environment receiver is not installed" >&2
	exit 127
fi

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
	exec "$1" "$2" "$3"
' set-tmux-env "$python_command" "$receiver" "$tmux_command"
