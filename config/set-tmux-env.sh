#!/bin/sh
# tmux, annoyingly, does not read startup files :(
# this matters when starting a new tmux session from ssh, where no environment variables are set by default
env -i TERM="$TERM" PS1='; ' zsh --no-rcs --no-globalrcs -c '. ~/.profile && export PATH && export' | grep -E '^(EDITOR|VISUAL|PATH)=' | tr = '\n' | xargs -n2 tmux set-environment -g
