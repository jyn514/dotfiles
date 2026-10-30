#!/bin/sh
printf '%s\n' "$*" >> "$TMUX_CALLS"
case "$1" in
	has-session) exit 1 ;;
	new-session) printf '%%7\n' ;;
	display-message) exit 27 ;;
esac
