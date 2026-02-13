# docs: https://fishshell.com/docs/current/, or `help` for local docs
# debugging: fish_trace=1 (like set -x)
# profiling: --profile-startup
# completion: --debug=complete
# all debug categories: --print-debug-categories
# keymap: `bind`; see `bind --list-modes`

# if [ -x /usr/bin/lesspipe ]
# 	eval (set SHELL /bin/sh lesspipe)
# end

umask 077

set DOTFILES (dirname (dirname (realpath ~/.profile)))

function add_path
	fish_add_path --global --move --prepend $argv
end

function add_path_if_present
	if [ -d $argv[1] ]
		add_path $argv[1]
	end
end

function exists
	command -q $argv[1]
end

if [ -f ~/.local/profile.fish ]
	. ~/.local/profile.fish
end

. $DOTFILES/lib/env.sh
. $DOTFILES/lib/paths.sh

if exists nvim
	export EDITOR=editor-hax
	export LESSEDIT='%E %g?lm\:%lm'
	# julia has AWFUL defaults and doesn't wait for the editor to exit if it doesn't recognize it
	# https://github.com/JuliaLang/julia/blob/083bd8f687bb2a0608a1b0b4c99f811eecb56b3e/stdlib/InteractiveUtils/src/editless.jl#L49
	export JULIA_EDITOR=hx-hax
else
	export EDITOR=vi
	export JULIA_EDITOR=open
end
export VISUAL=$EDITOR

if [ -x /home/linuxbrew/.linuxbrew/bin/brew ]
	/home/linuxbrew/.linuxbrew/bin/brew shellenv fish | source
end

if not status --is-interactive
	exit
end

## options

export HAVE_BROKEN_WCWIDTH 0
set GITHUB 'https://github.com/'
set MY_GITHUB 'https://github.com/jyn514'
set SRC "/usr/local/src"

# https://fishshell.com/docs/current/cmds/set_color.html
set fish_color_comment white --dim
set -g fish_greeting

## keybinds

# https://fishshell.com/docs/current/interactive.html#vi-mode-commands
# Use emacs keybinds in insert mode
fish_hybrid_key_bindings

function get_fzf_selection
	set -l bindings
	for key in enter tab ctrl-o ctrl-y ctrl-l
		set -a bindings "$key:replace-query+print($key)+accept-or-print-query"
	end
	fzf --bind "$(string join , $bindings)" $argv
end

function fzf_action
	get_fzf_selection | read --line key selection
	set selection (string escape $selection)
	switch $key
		case enter
			commandline -i $selection
			commandline -f execute
		case tab
			commandline -i $selection
		case ctrl-y
			printf %s $selection | copy
		case ctrl-o
			commandline -r open
			commandline -i " $selection"
			commandline -f execute
		case ctrl-l
			commandline -r $EDITOR
			commandline -i " $selection"
			commandline -f execute
	end
end

bind -M insert alt-e '$EDITOR ~/.config/fish/config.fish'
bind -M insert alt-r 'source ~/.config/fish/config.fish'
bind -M insert alt-shift-e edit_command_buffer
bind -M insert alt-t 'fd | fzf_action'
bind -M insert ctrl-o 'fd | fzf_action'
bind -M insert alt-k \
	'for cmd in sudo doas please run0
		if command -q $cmd
			fish_commandline_prepend $cmd
			break
		end
	end'

# load common aliases
grep -Ev '^(#|$)' $DOTFILES/lib/abbr.txt | while read --line alias
	echo $alias | read --delimiter = name value
	if [ $name = cat ]; continue; end
	abbr --add --global $name $value
end

# load git aliases
git config --get-regexp 'alias\.' | string replace --regex '^alias.' '' | while read --delimiter ' ' name value
	if set actual $(string match --groups-only --regex '^!(.*)' -- $value)
		abbr --add --global "g$name" -- "$actual"
	else
		abbr --add --global --command git $name -- $value
	end
end

# load cargo aliases
cargo --list | tail -n+2 | while read name value
	set value $(string trim $value)
	if set expansion $(string match --groups-only --regex '^alias: (.*)' -- $value)
		echo "alias: cargo $name=$expansion"
		abbr --add --global --command cargo $name -- $expansion
		set cmd expansion
	else
		set cmd $name
	end
	if contains $name c d; continue; end
	abbr --add --global "c$name" -- "cargo $expansion"
end

function cat; bat -p $argv; end
function fork-github
	cd (command fork-github $argv)
end
function ip
	functions --erase ip
	if command ip --color -V >/dev/null 2>&1
		abbr --add --global ip 'ip --color'
		command ip --color $argv
	else
		command ip $argv
	end
end
function which
	if not isatty 1
		command which $argv
		return
	end
	if [ (count $argv) = 0 ]
		echo "usage: which [<abbr|builtin|function|command>...]" >&2
		return 1
	end
	if test $argv[1] = -a
		set all 1
		set --erase argv[1]
	end
	for cmd in $argv
		set t (type -t $cmd 2>/dev/null)
		if [ "$t" = function ] || [ "$t" = builtin ]
			if test "$all" = 1
				type --all $cmd
			else
				type $cmd
			end
		else if abbr --query $cmd  # this doesn't catch regex-based abbreviations :(
			set -l tokens
			if abbr --show | grep -F -- "abbr -a -- $cmd " | read --tokenize --list tokens
				echo "$cmd is an abbreviation to: $tokens[-1]"
			else
				printf %s "$cmd is a abbreviation: "
				abbr --show | grep --color=never -F -- "-- $cmd"
			end
		else
			if test "$all" = 1
				command --all --search $cmd
			else
				command --search $cmd
			end
			or fish_command_not_found $cmd
		end
	end
end

# load custom syntax

function last_history_line
	echo $history[1]
end

function expand_history_line
	switch $argv[1]
		case !!
			echo $history[1]
		case "!-*"
			echo $history[(string split - $argv[1])[2]]
		case "*"
			return 1
	end
end

function bind_dollar
	switch (commandline -ct)
	case '*!' # !$
		# https://github.com/fish-shell/fish-shell/wiki/Bash-Style-Command-Substitution-and-Chaining-(!!-!$)
		commandline -f backward-delete-char history-token-search-backward
	case '*$' # $$
		commandline -i fish_pid
	case '*'
		commandline -i '$'
	end
end

function bind_qmark
	switch (commandline -ct)
	case '*$'  # $?
		commandline -i status
	case '*'
		commandline -i '?'
	end
end

abbr --add --global !!      --position anywhere --function expand_history_line
abbr --add --global history --position anywhere --regex '!-[0-9]+'  --function expand_history_line

# https://github.com/fish-shell/fish-shell/issues/11710
bind --mode insert '$' bind_dollar
bind --mode insert '?' bind_qmark

## functions and builtin hooks

function pure_shell
	env -i HOME="$HOME" TERM="$TERM" PS1='; ' DISPLAY="$DISPLAY" fish --no-config \
		--init-command 'function fish_prompt; echo "; "; end' \
		$argv
 end

if status is-login
	set fish_name -fish
else
	set fish_name fish
end

function fish_prompt
	prompt-command $fish_name $status
end

function fish_mode_prompt
	if [ "$fish_key_bindings" = fish_vi_key_bindings ]
		or [ "$fish_key_bindings" = fish_hybrid_key_bindings ]

		set_color --bold cyan
		switch $fish_bind_mode
			case default
				echo '[N]'
			case insert
				echo '[I]'
			case replace_one
				echo '[R]'
			case replace
				echo '[R]'
			case visual
				echo '[V]'
		end
		set_color normal
		printf ' '
	end
end

set duration 0
set time "00:00"
function record_duration --on-event fish_postexec
	set duration $CMD_DURATION
end

function fish_right_prompt
	set -l width 0

	if [ "$duration" -gt 9 ]
		set_color white --dim
		set -l minp $(printf "%.2g" $(math $duration/1000))
		set -l maxp $(printf "+%.4ss" $minp)
		set s $maxp
		set width (string length --visible $s)
	end

	printf "\e[1A"

	set t (date +%H:%M)
	if ! [ "$t" = "$time" ]
		set time $t
		printf "\e[2;37m%s" $t
	else if [ $width -gt 0 ]
		# printf "\e[1A"
		string repeat -n $width ' '
		printf '%s' $s
		# printf "\e[1B"
	end

	printf "\e[1B"
	set duration 0
end

function fish_command_not_found
	if [ -e $DOTFILES/lib/command-not-found ]
		$DOTFILES/lib/command-not-found $argv
	else
		__fish_default_command_not_found_handler $argv
	end
end

atuin init fish --disable-up-arrow | source
bind -M default / _atuin_search

zoxide init fish | source
function cd; z $argv; end

if exists direnv
	direnv hook fish | source
end

nvm use --silent lts

stty -ixon

[ -x ~/.local/startup-hook ] && ~/.local/startup-hook
# `exit` in fish only exits the file, not the shell as a whole.
[ $status = 120 ] && exec true
