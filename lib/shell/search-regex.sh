#!/bin/sh

word_start='(^|[[:space:]"])'
context_start='[[:space:]"]'

relative_path='(\.|\.\.)'
word_path='[[:alnum:]_][.[:alnum:]~_"-]*'
nonword_path="($relative_path|~|\.$word_path)"
path_start="($word_path|$nonword_path)"

component='[][[:alnum:]_.#$%&+=@"-]'
intermediate_path="(/$component+)"
line_no='(:[0-9]+)'
position="$line_no$line_no?"
extension_file="$component*\.$component+"
# Keep the explicit end-of-line alternative. On macOS, tmux's BSD regex engine
# failed to match filenames ending at the line boundary when this used only the
# GNU-style \> assertion, although directories still matched. Linux tmux tests
# did not reproduce that failure.
path_end='(\>|$)'

with_extension="${intermediate_path}*/$extension_file($position)?$path_end"
with_position="${intermediate_path}*/$component+$position$path_end"
deep_path="${intermediate_path}{2,}($path_end|[[:space:]])"
directory="${intermediate_path}+/"
path_tail="($with_extension|$with_position|$deep_path|$directory)"

relative_file="($relative_path/$component+($position)?$path_end)"
executable_path="((bin|sbin|libexec)/$component+$path_end)"
bare_file="$component+\.$component+$position:"

word_candidate="($path_start$path_tail|$relative_file|$executable_path|$bare_file)"
context_candidate="($path_start$path_tail|$path_tail|$relative_file|$executable_path)"

# Diagnostic formats emitted by compilers, test runners, and stack traces.
diagnostic_file='[][[:alnum:]_./~#$%&+=@"-]+'
parenthesized_colon="\\($diagnostic_file$position\\)"
comma_position="$diagnostic_file\\([0-9]+,[0-9]+\\)"
parenthesized_comma="\\($comma_position\\)"
traceback="File \"$diagnostic_file\", line [0-9]+"
line_word="$component+\\.$component+ line [0-9]+:"
bare_diagnostic="CMakeLists\\.txt${position}[[:space:]]"

diagnostic_candidate="($parenthesized_colon|$parenthesized_comma|$comma_position|$traceback|$line_word|$bare_diagnostic)"

# Require a separated token: a word boundary also occurs after URL slashes.
# tmux's regex engine has no lookbehind, so the match consumes its separator;
# open normalizes that delimiter before dispatch.
regex="($diagnostic_candidate|^$path_tail|$word_start$word_candidate|$context_start$context_candidate)"

# Behavioral coverage uses tmux's regex engine directly; see
# tests/tmux/search_regex_test.py.
echo "$regex"
