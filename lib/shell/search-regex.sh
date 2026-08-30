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

# Behavioral coverage uses tmux's regex engine directly; see
# tests/tmux/search_regex_test.py.
echo "$regex"
