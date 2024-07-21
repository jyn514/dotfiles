#!/bin/sh
# switch to the first detached session, if it exists
target=$(tmux list-sessions -f '#{?session_attached,0,1}' -F '#{session_id}' | head -n1)
if [ "$target" ]; then
  # TODO: can we avoid spawning a shell just to immediately kill it?
  tmux set-option destroy-unattached
  tmux switch-client -t "$target"
fi
