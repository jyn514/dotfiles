cd -- "$FORK_START_DIRECTORY"; or exit
fork-github $argv
set -l fork_status $status
printf '%s\0' "$PWD"
exit $fork_status
