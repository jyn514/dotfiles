#!/bin/sh
start_delim='(^|/|\<|[[:space:]"])'

relative_path='(\.|\.\.)'
start_path="($relative_path|[[:alnum:]~_\"-]*)"

component='[][[:alnum:]_.#$%&+=@"-]'
intermediate_paths="(/$component+)"

line_no='(:[0-9]+)'
file_end="($component+$line_no?$line_no?)"
end="([/ \"]|\.$file_end|$component+$line_no$line_no?)"

regex="$start_delim$start_path(${intermediate_paths}+$end|${intermediate_paths}{2,}$end?|$relative_path/$file_end)"

echo "$regex"

# test cases; see https://regex101.com/r/Ct2v7A/1
test_case() {
	input="$1"
	expected="$2"
	ignored=${3:-}
	actual=$(echo "$input" | grep -oP "$regex")
	v=$(
		echo "Testing: '$input'"
		echo "Expected: '$expected'"
		echo "Actual:   '$actual'"
	)

	if [ "$(echo "$actual" | sed 's/^\s*//; s/\s*$//')" = "$expected" ]; then
		if [ "$ignored" = i ]; then
			printf "i"
		else
			printf "✓"
		fi
	else
		printf "\n✗ FAIL\n"
		echo "$v"
	fi >&2
}

# tests that should match
test_case "Error in /usr/local/etc/filename.txt at line 42" "/usr/local/etc/filename.txt"
test_case "Check foo/something.conf for settings" "foo/something.conf"
test_case "See ./foo.txt for details" "./foo.txt"
test_case "bin/foo:12 contains the error" "bin/foo:12"
test_case "./foo.txt:12: syntax error here" "./foo.txt:12"
test_case "Navigate to foo/bar/baz directory" "foo/bar/baz"
test_case "Running bin/foo without path" "bin/foo"
test_case "/usr/local/etc/filename.txt" "/usr/local/etc/filename.txt"
test_case "foo/something.conf" "foo/something.conf"
test_case "./foo.txt" "./foo.txt"
test_case "bin/foo:12" "bin/foo:12"
test_case "bin/foo:12:" "bin/foo:12"
test_case "./foo.txt:12" "./foo.txt:12"
test_case "./foo.txt:12:" "./foo.txt:12"
test_case "foo/bar/baz/" "foo/bar/baz/"
test_case "10:59:58 ~/jyn/dotfiles main" "~/jyn/dotfiles"
test_case "11:01:55 ~/jyn/dotfiles main" "~/jyn/dotfiles"

# tests that should not match
# (consider 'if foo.bar {}' in source code or 'origin/main' in a git command)
test_case "Variable x.y.z is undefined" ""
test_case "Simple word foo without context" ""
test_case "x.y.z" ""
test_case "foo" ""
test_case "x.y.z:12" ""
test_case "something.conf" ""
test_case "Just some text with something.conf mentioned" ""
test_case "bin/foo" ""

# todo
# test_case "copycat.tmux:43:    tmux list-keys" "copycat.tmux:43"
test_case "copycat.tmux:43:    tmux list-keys" "" i
# test_case "foo/bar/baz" "foo/bar/baz"
test_case "foo/bar/baz" "foo/bar/" i

echo >&2
