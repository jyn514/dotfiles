#!/usr/bin/env bash
set -e

session_names=$(tmux list-sessions -F '#{session_name}')
numeric=()
while IFS= read -r name; do
  [[ $name =~ ^[0-9]+$ ]] && numeric+=("$name")
done <<< "$session_names"
[ "${#numeric[@]}" -gt 0 ] || exit 0

sorted=$(printf '%s\n' "${numeric[@]}" | sort -n)
old_names=()
while IFS= read -r name; do
  old_names+=("$name")
done <<< "$sorted"
temporary="__renumber-tmux-$$-$RANDOM-"
recovery="__renumber-tmux-recovery-$$-$RANDOM-"

moved=0
for old in "${old_names[@]}"; do
  new=$((moved + 1))
  if tmux rename-session -t "$old" "$temporary$new"; then
    :
  else
    status=$?
    set +e
    while [ "$moved" -gt 0 ]; do
      tmux rename-session -t "$temporary$moved" "${old_names[moved - 1]}"
      moved=$((moved - 1))
    done
    exit "$status"
  fi
  moved=$((moved + 1))
done

count=${#old_names[@]}
new=1
while [ "$new" -le "$count" ]; do
  if tmux rename-session -t "$temporary$new" "$new"; then
    :
  else
    status=$?
    set +e
    index=1
    while [ "$index" -le "$count" ]; do
      if [ "$index" -lt "$new" ]; then
        current=$index
      else
        current=$temporary$index
      fi
      tmux rename-session -t "$current" "$recovery$index"
      index=$((index + 1))
    done
    index=1
    while [ "$index" -le "$count" ]; do
      tmux rename-session -t "$recovery$index" "${old_names[index - 1]}"
      index=$((index + 1))
    done
    exit "$status"
  fi
  new=$((new + 1))
done
