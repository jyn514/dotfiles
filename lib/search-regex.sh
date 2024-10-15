#!/bin/sh
start_delim='(^|[[:space:]])'
relative_path='(\.|\.\.)'
start_path="($relative_path|[[:alnum:]~_-]*)"
component='[][[:alnum:]_.#$%&+=@-]'
intermediate_paths="(/$component+)"
line_no='(:[0-9]+)'
file_end="($component+$line_no?$line_no?)"
end="(/|\.$file_end|$component+$line_no$line_no?)"
echo "$start_delim$start_path(${intermediate_paths}+$end|${intermediate_paths}{2,}$end?|$relative_path/$file_end)"

# test cases; see https://regex101.com/r/Ct2v7A/1
: "
# these match
/usr/local/etc/filename.txt
foo/something.conf
./foo.txt
bin/foo:12
bin/foo:12:
./foo.txt:12
./foo.txt:12:
foo/bar/baz
# these don't match (consider 'if foo.bar {}' in source code or 'origin/main' in a git command)
something.conf
bin/foo
x.y.z
foo
# ideally this would match but i haven't gotten around to it yet lol
x.y.z:12
copycat.tmux:43:                tmux list-keys
"
