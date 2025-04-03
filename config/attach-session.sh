#!/bin/sh

# this script messes up tmux-resurrect quite a lot. don't run it when restoring.
case "$1" in
  disable) tmux set-option  -s  @attach-session-disable 1;;
  enable)  tmux set-option  -su @attach-session-disable;;
  *)    if tmux show-option -sv @attach-session-disable 2>/dev/null; then exit 0; fi;;
esac

# if we're coming from another session the empty session is intentional; don't override the explicit command.
if [ "$(tmux display-message -p '#{client_last_session}' | tr -d '\n')" ]; then
  exit 0
fi

# if *this* is a detached session, it was almost certainly created programmatically.
# don't mess with scripts.
if [ "$(tmux display-message -p '#{session_attached}' | tr -d '\n')" = 0 ]; then
	exit 0
fi

# switch to the first detached session, if it exists
target=$(tmux list-sessions -f '#{?session_attached,0,1}' -F '#{session_id}' | head -n1)
if [ "$target" ]; then
  tmux set-option destroy-unattached
  tmux switch-client -t "$target"
fi
