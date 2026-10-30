source "$PROFILE_FISH"; or exit
set -l tokens
abbr --show | grep -F -- 'abbr -a -- mkdc ' | read --tokenize --list tokens
or exit 1
# Execute the registered expansion in this shell, not a child that loses cd.
eval $tokens[-1] (string escape -- $argv)
set -l execution_status $status
printf '%s\n%s\n' $execution_status "$PWD"
