#!/bin/sh
# Model the first created resource disappearing before the next host arrives.
printf '%s\n' "$*" >> "$TMUX_CALLS"
created=0
if [ -r "$TMUX_STATE" ]; then
	read -r created < "$TMUX_STATE"
fi
case "$1" in
	has-session)
		[ "$3" = current ] || [ "$created" -ge 2 ]
		;;
	display-message)
		if [ "$3" = -t ]; then
			printf '@%s\n' "$created"
		else
			printf 'current\n'
		fi
		;;
	list-windows)
		if [ "$created" -ge 2 ]; then
			printf 'cssh-0\n'
		fi
		;;
	new-session|new-window)
		created=$((created + 1))
		printf '%s\n' "$created" > "$TMUX_STATE"
		printf '%%%s\n' "$created"
		;;
	split-window) printf '%%3\n' ;;
esac
