#!/bin/sh

# this script messes up tmux-resurrect quite a lot. don't run it when restoring.
case "$1" in
  disable) exec tmux set-option  -s  @attach-session-disable 1;;
  enable)  exec tmux set-option  -su @attach-session-disable;;
  *)    if tmux show-option -sv @attach-session-disable 2>/dev/null; then exit 0; fi;;
esac

# if we're coming from another session the empty session is intentional; don't override the explicit command.
last_session=$(tmux display-message -p '#{client_last_session}') || exit
if [ -n "$last_session" ]; then
  exit 0
fi

# if *this* is a detached session, it was almost certainly created programmatically.
# don't mess with scripts.
session_attached=$(tmux display-message -p '#{session_attached}') || exit
if [ "$session_attached" = 0 ]; then
	exit 0
fi

# switch to the first detached session, if it exists
sessions=$(tmux list-sessions -f '#{?session_attached,0,1}' -F '#{session_id}') || exit
IFS='
'
set -f
# shellcheck disable=SC2086  # Select the first newline-delimited session ID.
set -- $sessions
target=${1:-}
if [ "$target" ]; then
  tmux set-option destroy-unattached
  tmux switch-client -t "$target"
fi
