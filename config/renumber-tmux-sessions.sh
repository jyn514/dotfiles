#!/usr/bin/env bash
sessions=$(tmux list-sessions -F '#{session_name}' | grep '^[0-9]\+$' | sort)
new=1
for old in $sessions
do
  tmux rename -t "$old" $new
  ((new++))
done
