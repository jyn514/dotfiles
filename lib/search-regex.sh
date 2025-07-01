#!/bin/sh

regex='((\.|\.\.)(\/[[:alnum:]_.#$%&+=@"-]+)+|(\.\/|\.\.\/)[[:alnum:]_.#$%&+=@"-]+|[[:alnum:]~_.#$%&+=@"-]*\/[[:alnum:]_.#$%&+=@"-]+(\/[[:alnum:]_.#$%&+=@"-]+)*|[[:alpha:]][[:alnum:]_-]*\.[[:alpha:]]{2,}[[:alnum:]_-]*)((:[0-9]+){1,2}:?)?'
echo "$regex"

test_case() {
   local input="$1"
   local expected="$2"
   local actual
   actual=$(echo "$input" | ggrep -oP "$regex")

   echo "Testing: '$input'"
   echo "Expected: '$expected'"
   echo "Actual:   '$actual'"

   if [ "$actual" = "$expected" ]; then
       echo "✓ PASS"
   else
       echo "✗ FAIL"
   fi
   echo
}

# tests that should match
test_case "Error in /usr/local/etc/filename.txt at line 42" "/usr/local/etc/filename.txt"
test_case "Check foo/something.conf for settings" "foo/something.conf"
test_case "See ./foo.txt for details" "./foo.txt"
test_case "bin/foo:12 contains the error" "bin/foo:12"
test_case "./foo.txt:12: syntax error here" "./foo.txt:12:"
test_case "Navigate to foo/bar/baz directory" "foo/bar/baz"
test_case "Just some text with something.conf mentioned" "something.conf"
test_case "Running bin/foo without path" "bin/foo"
test_case "/usr/local/etc/filename.txt" "/usr/local/etc/filename.txt"
test_case "foo/something.conf" "foo/something.conf"
test_case "./foo.txt" "./foo.txt"
test_case "bin/foo:12" "bin/foo:12"
test_case "bin/foo:12:" "bin/foo:12:"
test_case "./foo.txt:12" "./foo.txt:12"
test_case "./foo.txt:12:" "./foo.txt:12:"
test_case "foo/bar/baz" "foo/bar/baz"
test_case "something.conf" "something.conf"
test_case "bin/foo" "bin/foo"
test_case "copycat.tmux:43:                tmux list-keys" "copycat.tmux:43:"
test_case "10:59:58 ~/leo/dotfiles main" "~/leo/dotfiles"
test_case "11:01:55 ~/leo/dotfiles main" "~/leo/dotfiles"

# tests that should not match
test_case "Variable x.y.z is undefined" ""
test_case "Simple word foo without context" ""
test_case "x.y.z" ""
test_case "foo" ""
test_case "x.y.z:12" ""
