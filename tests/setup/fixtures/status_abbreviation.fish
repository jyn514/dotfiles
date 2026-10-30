source "$PROFILE_FISH"; or exit
# Keep provider selection private to this fixture, after the complete loader.
set -gx PATH "$PROFILE_TEST_BIN" "$DOTFILES/bin" /usr/bin /bin
set -l tokens
abbr --show | grep -F -- 'abbr -a -- s ' | read --tokenize --list tokens
or exit 1
printf 'expansion=%s\n' "$tokens[-1]"
# The registered shell text, including arguments, is what the reader executes.
printf 'consumer_begin\n'
eval $tokens[-1]
set -l execution_status $status
printf 'consumer_end=%s\n' $execution_status
# Do not shadow Fish's native status: configuration depends on this builtin.
printf 'status_type=%s\n' (type --type status)
builtin status --is-interactive; or exit
status --is-interactive; or exit
printf 'builtin_status_available\n'
