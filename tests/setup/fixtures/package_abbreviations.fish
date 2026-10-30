source "$PROFILE_FISH"; or exit
set -gx PATH "$PROFILE_TEST_BIN" $PATH
set -l tokens
abbr --show | grep -F -- "abbr -a -- $argv[1] " | read --tokenize --list tokens
or exit 1
# Resolve the registered value as Fish does, including functions and builtins.
type --type -- $tokens[-1]; or exit
command --search -- $tokens[-1]; or exit
# Abbreviations expand before execution; eval runs that registered shell text.
eval $tokens[-1] (string escape -- $argv[2])
