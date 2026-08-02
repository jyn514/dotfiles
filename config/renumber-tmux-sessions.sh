#!/usr/bin/env bash
set -e

session_names=$(tmux list-sessions -F '#{session_name}')
sessions=$(printf '%s\n' "$session_names" | awk '/^[0-9]+$/' | sort -n)
temporary="__renumber-tmux-$$-"
new=1
for old in $sessions
do
  tmux rename-session -t "$old" "$temporary$new"
  ((new++))
done

count=$new
new=1
while [ "$new" -lt "$count" ]
do
  tmux rename-session -t "$temporary$new" "$new"
  ((new++))
done
