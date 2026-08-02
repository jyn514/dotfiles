#!/bin/sh
set -e

# Claude Code statusLine: reuse the dotfiles PS1 driver (prompt-command).
# Model name takes the "shell@host" slot; cwd drives git/jj info.
# Strip \01/\02 readline non-print markers (PS1-only; literal bytes in a statusline).

input=$(cat)
cwd=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // empty')
model=$(printf '%s' "$input" | jq -r '.model.display_name // "claude"')
used=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty')

if [ -n "$cwd" ]; then
  cd "$cwd" 2>/dev/null || exit 1
fi
prompt_command=$(command -v prompt-command) || exit
[ -n "$used" ] && printf ' ctx:%s%% ' "$(printf '%.0f' "$used")"

# prompt-command emits a second prompt line ("; "); keep only the first line.
# (GIT_OPTIONAL_LOCKS is set inside prompt-command's git_info now.)
prompt=$("$prompt_command" "$model" 0) || exit
prompt=$(printf '%s\n' "$prompt" | tr -d '\001\002') || exit
prompt=$(printf '%s\n' "$prompt" | sed -n '1p') || exit
printf '%s' "$prompt"
