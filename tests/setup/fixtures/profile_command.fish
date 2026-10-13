source "$PROFILE_FISH"; or exit
if test -n "$PROFILE_TEST_BIN"
	set -gx PATH "$PROFILE_TEST_BIN" $PATH
end
set -l profile_test_command $argv[1]
set -e argv[1]
eval $profile_test_command
