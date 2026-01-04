# docs: https://fishshell.com/docs/current/, or `help` for local docs
# debugging: fish_trace=1 (like set -x)
# profiling: --profile-startup
# completion: --debug=complete
# all debug categories: --print-debug-categories
# keymap: `bind`; see `bind --list-modes`

if [ -x /usr/bin/lesspipe ]
	eval (set SHELL /bin/sh lesspipe)
end

umask 077

set DOTFILES (dirname (dirname (realpath ~/.profile)))

function add_path
	if not contains $argv[1] $PATH
		set PATH $argv[1] $PATH
	end
end

function add_path_if_present
	if [ -d $argv[1] ]
		add_path $argv[1]
	end
end

function exists
	command -q $argv[1]
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

bind -M insert alt-e '$EDITOR ~/.config/fish/config.fish'
bind -M insert alt-r 'source ~/.config/fish/config.fish'
bind -M insert alt-shift-e edit_command_buffer
bind -M insert alt-t 'commandline -i (fd | fzy); commandline -f repaint'
bind -M insert alt-shift-t \
	'set --local f (fd | fzy)
	 set --local worked $status
	 commandline -f repaint
	 if [ $worked = 0 ]
		commandline -i "$EDITOR $f"
		commandline -f execute
	 end'

bind -M insert alt-k \
	'for cmd in sudo doas please run0
		if command -q $cmd
			fish_commandline_prepend $cmd
			break
		end
	end'

# load common aliases
grep -Ev '^(#|$)' $DOTFILES/lib/abbr.txt | while read -L alias
	echo $alias | read --delimiter = name value
	if [ $name = cat ]; continue; end
	abbr --add --global $name $value
end
function cat; bat -p $argv; end
function fork-github
	cd (command fork-github $argv)
end
function ip
	functions --erase ip
	if command ip --color -V >/dev/null 2>&1
		abbr --add --global ip 'ip --color'
		ip --color $argv
	else
		ip $argv
	end
end
function which
	for cmd in $argv
		set t (type -t $cmd 2>/dev/null)
		if [ "$t" = function ] || [ "$t" = builtin ]
			type $cmd
		else
			command -v $cmd
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

	if [ $width -gt 0 ]
		printf "\e[1A"
		string repeat -n $width ' '
		printf '%s' $s
		printf "\e[1B"
	end

	set t (date +%H:%M)
	if ! [ "$t" = "$time" ]
		set time $t
		printf "\e[2;37m%s" $t
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
atuin gen-completions --shell fish | source
bind -M default / _atuin_search

zoxide init fish | source
function cd; z $argv; end

nvm use --silent lts

stty -ixon
