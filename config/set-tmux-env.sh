#!/bin/sh
# tmux, annoyingly, does not read startup files :(
# this matters when starting a new tmux session from ssh, where no environment variables are set by default
env -i HOME="$HOME" TERM="$TERM" PS1='; ' bash --noprofile --norc -c '. ~/.profile && export PATH && printenv' \
	| grep -E '^(EDITOR|VISUAL|PATH)=' \
	|  tr = '\n' | xargs -n2 tmux set-environment -g
