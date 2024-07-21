#!/bin/sh

# if we're coming from another session the empty session is intentional; don't override the explicit command.
if [ "$(tmux display-message -p '#{client_last_session}' | tr -d '\n')" ]; then
  exit 0
fi

# switch to the first detached session, if it exists
target=$(tmux list-sessions -f '#{?session_attached,0,1}' -F '#{session_id}' | head -n1)
if [ "$target" ]; then
  # TODO: can we avoid spawning a shell just to immediately kill it?
  tmux set-option destroy-unattached
  tmux switch-client -t "$target"
fi
