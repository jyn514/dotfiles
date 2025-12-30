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

. $DOTFILES/lib/paths.sh

if not status --is-interactive
	exit
end

## options

export HAVE_BROKEN_WCWIDTH 0

# https://fishshell.com/docs/current/cmds/set_color.html
set fish_color_comment white --dim

## keybinds

# https://fishshell.com/docs/current/interactive.html#vi-mode-commands
# Use emacs keybinds in insert mode
fish_hybrid_key_bindings

bind --preset -M insert alt-k \
	'for cmd in sudo doas please run0
		if command -q $cmd
			fish_commandline_prepend $cmd
			break
		end
	end'

# load env
. $DOTFILES/lib/env.sh
set GITHUB 'https://github.com/'
set MY_GITHUB 'https://github.com/jyn514'
set SRC "/usr/local/src"

# load common aliases
grep -Ev '^(#|$)' $DOTFILES/lib/abbr.txt | while read -L alias
	echo $alias | read --delimiter = name value
	if [ $name = cat ]; continue; end
	abbr --add --global $name $value
end
function cat; bat $argv; end

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

function pure_shell
	env -i HOME="$HOME" TERM="$TERM" PS1='; ' DISPLAY="$DISPLAY" fish --no-config \
		--init-command 'function fish_prompt; echo "; "; end' \
		$argv
 end

function fish_name
	if status is-login
		echo -fish
	else
		echo fish
	end
end

function fish_prompt
	prompt-command (fish_name)
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

atuin init fish --disable-up-arrow | source
atuin gen-completions --shell fish | source
bind -M default / _atuin_search

zoxide init fish | source
function cd; z $argv; end

stty -ixon
