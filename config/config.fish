# docs: https://fishshell.com/docs/current/, or `help` for local docs
# debugging: fish_trace=1 (like set -x)
# profiling: --profile-startup
# completion: --debug=complete
# all debug categories: --print-debug-categories
# keymap: `bind`; see `bind --list-modes`

# if [ -x /usr/bin/lesspipe ]
# 	eval (set SHELL /bin/sh lesspipe)
# end

set -l profile_path (realpath ~/.profile); or return
set DOTFILES (dirname (dirname $profile_path)); or return
set -e profile_path

# fish 3 doesn't support most `abbr` and `complete` arguments :/
if string match -q "3.*" $FISH_VERSION
	echo "ignoring abbr/complete on fish 3"
	export old_fish=1
end

if [ -n "$old_fish" ]
  function abbr
  end
  #function complete
  #end
  function add_path
	set PATH "$argv:$PATH"
  end
else
	function add_path
		fish_add_path --global --move --prepend $argv
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

function source_init
	set --local init_output (command $argv)
	or return
	printf '%s\n' $init_output | source
	or return
end

if [ -f ~/.local/profile.fish ]
	. ~/.local/profile.fish
	or return
end

. $DOTFILES/lib/shell/env.sh; or return
. $DOTFILES/lib/shell/paths.sh; or return

# compat for old `bat` versions
if exists bat; and string match --quiet --regex "0\.1[0-9]\." (bat --version)
	echo "ignoring 'rule' for old bat versions"
	export BAT_STYLE=changes,header
end

if exists nvim
	export EDITOR=editor-hax
	export LESSEDIT='%E %g?lm\:%lm'
	# julia has AWFUL defaults and doesn't wait for the editor to exit if it doesn't recognize it
	# https://github.com/JuliaLang/julia/blob/083bd8f687bb2a0608a1b0b4c99f811eecb56b3e/stdlib/InteractiveUtils/src/editless.jl#L49
	export JULIA_EDITOR=editor-hax
else
	export EDITOR=vi
	export JULIA_EDITOR=open
end
export VISUAL=$EDITOR

if [ -x /home/linuxbrew/.linuxbrew/bin/brew ]
	set -l brew_command /home/linuxbrew/.linuxbrew/bin/brew
	set -l brew_cache ~/.local/config/brew.fish
	set -l generated_brew_cache
	if ! [ -e $brew_cache ]; or [ $brew_command -nt $brew_cache ]
		set -l pending_cache "$brew_cache.$fish_pid"
		command mkdir -p (dirname $brew_cache); or return
		if $brew_command shellenv fish > $pending_cache
			if . $pending_cache
				command mv $pending_cache $brew_cache; or return
				set generated_brew_cache 1
			else
				set -l brew_status $status
				command rm -f $pending_cache
				return $brew_status
			end
		else
			set -l brew_status $status
			command rm -f $pending_cache
			return $brew_status
		end
	end
	if not set -q generated_brew_cache
		. $brew_cache; or return
	end
end

if [ -z "$SSH_AUTH_SOCK" ]
	set -l kernel (uname); or return
	if [ "$kernel" = Darwin ]
		export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
	else
		export SSH_AUTH_SOCK=$HOME/.1password/agent.sock
	end
end

if not status --is-interactive
	return
end

if set -q KITTY_INSTALLATION_DIR
	set --global KITTY_SHELL_INTEGRATION enabled
	source "$KITTY_INSTALLATION_DIR/shell-integration/fish/vendor_conf.d/kitty-shell-integration.fish"
	or return
	set -l kitty_completions "$KITTY_INSTALLATION_DIR/shell-integration/fish/vendor_completions.d"
	if not contains -- $kitty_completions $fish_complete_path
		set --prepend fish_complete_path $kitty_completions
	end
end

if exists mise
	set --erase MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH
	while set --local shim_index (contains --index -- "$HOME/.local/share/mise/shims" $PATH)
		set --erase PATH[$shim_index]
	end
	source_init mise activate fish
	or return
end

## options

export HAVE_BROKEN_WCWIDTH=0
set GITHUB 'https://github.com/'
set MY_GITHUB 'https://github.com/jyn514'
set SRC "/usr/local/src"

# https://fishshell.com/docs/current/cmds/set_color.html
set fish_color_comment white --dim
set -g fish_greeting

# load x.py completions at runtime
if not contains -- src/etc/completions $fish_complete_path
	set -a fish_complete_path src/etc/completions
end

## keybinds

# https://fishshell.com/docs/current/interactive.html#vi-mode-commands
# Use emacs keybinds in insert mode
fish_hybrid_key_bindings

function get_fzf_selection
	fzf --expect=tab,ctrl-o,ctrl-y,ctrl-l $argv
end

function fzf_action
	get_fzf_selection $argv | read --null --line key selection
	set -l statuses $pipestatus
	switch $statuses[1]
		case 0
		case 1 130
			return 0
		case '*'
			return $statuses[1]
	end
	[ $statuses[2] -eq 0 ]; or return $statuses[2]
	if [ -z "$key" ]
		set key enter
	end
	set -l escaped_selection (string escape -- $selection)
	switch $key
		case enter
			commandline -i $escaped_selection
			commandline -f execute
		case tab
			commandline -i $escaped_selection
		case ctrl-y
			printf %s $selection | copy
		case ctrl-o
			commandline -r open
			commandline -i " $escaped_selection"
			commandline -f execute
		case ctrl-l
			commandline -r $EDITOR
			commandline -i " $escaped_selection"
			commandline -f execute
	end
end

function fzf_file_action
	fd --print0 | fzf_action --read0 --print0
	set -l statuses $pipestatus
	[ $statuses[1] -eq 0 ]; or return $statuses[1]
	return $statuses[2]
end

abbr --add --global :ec "$EDITOR ~/.config/fish/config.fish"
bind -M insert alt-e '$EDITOR ~/.config/fish/config.fish'
bind -M insert alt-r 'source ~/.config/fish/config.fish'
bind -M insert alt-shift-e edit_command_buffer
bind -M insert alt-t fzf_file_action
bind -M insert ctrl-o fzf_file_action
bind -M insert alt-k \
	'for cmd in sudo doas please run0
		if command -q $cmd
			fish_commandline_prepend $cmd
			break
		end
	end'

# load common aliases
set abbreviations (grep -Ev '^(#|$)' $DOTFILES/lib/abbr.txt)
or return
for alias in $abbreviations
	echo $alias | read --delimiter = name value
	if [ $name = cat ]; continue; end
	abbr --add --global $name $value
	or return
end
set --erase abbreviations

# load git aliases
if [ -z "$old_fish" ]
	set git_aliases (git config --get-regexp 'alias\.')
	or return
	for alias in $git_aliases
		string replace --regex '^alias.' '' -- $alias | read --delimiter ' ' name value
		if set actual (string match --groups-only --regex '^!(.*)' -- $value)
			abbr --add --global "g$name" -- "$actual"
		else
			abbr --add --global --command git $name -- $value
		end
		or return
	end
	set --erase git_aliases
end

abbr --add --global --command git -- -nv --no-verify

function reload_cargo_aliases
	set -l cargo_commands (cargo --list)
		or return
	for line in $cargo_commands[2..]
		echo $line | read -l name value
		set value (string trim $value)
		if set expansion (string match --groups-only --regex '^alias: (.*)' -- $value)
			set -l escaped_name (string escape -- "$name"); or return
			set -l escaped_expansion (string escape -- "$expansion"); or return
			printf 'abbr --add --command cargo %s -- %s\n' $escaped_name $escaped_expansion
			set cmd $expansion
		else
			set cmd $name
		end
		if contains $name c d; continue; end
		set -l escaped_short_name (string escape -- "c$name"); or return
		set -l escaped_short_expansion (string escape -- "cargo $cmd"); or return
		printf 'abbr --add --global %s -- %s\n' $escaped_short_name $escaped_short_expansion
	end
end

# load cargo aliases
if [ -z "$old_fish" ]; and exists cargo
	set -l cargo_alias_cache ~/.local/config/cargo.fish
	set -l cargo_command (command --search cargo)
	set -l generated_cargo_cache
	if ! [ -e $cargo_alias_cache ] \
			|| [ $DOTFILES/config/config.fish -nt $cargo_alias_cache ] \
			|| [ $cargo_command -nt $cargo_alias_cache ] \
			|| [ $CARGO_HOME/bin -nt $cargo_alias_cache ]
		set -l pending_cache "$cargo_alias_cache.$fish_pid"
		command mkdir -p (dirname $cargo_alias_cache)
		or return
		if reload_cargo_aliases > $pending_cache
			if . $pending_cache
				command mv $pending_cache $cargo_alias_cache
				or return
				set generated_cargo_cache 1
			else
				set -l reload_status $status
				command rm -f $pending_cache
				return $reload_status
			end
		else
			set -l reload_status $status
			command rm -f $pending_cache
			return $reload_status
		end
	end
	if not set -q generated_cargo_cache
		. $cargo_alias_cache
		or return
	end
end

if exists bat
	function cat; bat -p $argv; end
end
function fork-github
	set -l directory (command fork-github $argv)
		or return
	[ -n "$directory" ]
		or return 1
	cd $directory
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
			or __fish_default_command_not_found_handler $cmd
		end
	end
end

# load custom syntax

function last_history_line
	printf '%s\n' "$history[1]"
end

function expand_history_line
	switch $argv[1]
		case !!
			set -q history[1]
				or return 1
			printf '%s\n' "$history[1]"
		case "!-*"
			set -l offset (string split - $argv[1])[2]
			if [ $offset -lt 1 ] || [ $offset -gt (count $history) ]
				return 1
			end
			printf '%s\n' "$history[$offset]"
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
abbr --add --global history --position anywhere --regex '!-[1-9][0-9]*' --function expand_history_line
abbr --add --global - 'cd -'

# https://github.com/fish-shell/fish-shell/issues/11710
bind --mode insert '$' bind_dollar
bind --mode insert '?' bind_qmark

## functions and builtin hooks

function pure_shell
	env -i HOME="$HOME" TERM="$TERM" PS1='; ' DISPLAY="$DISPLAY" (which fish) --no-config \
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
				printf '[N]'
			case insert
				printf '[I]'
			case replace_one
				printf '[R]'
			case replace
				printf '[R]'
			case visual
				printf '[V]'
		end
		set_color normal
		printf ' '
	end
end

set duration 0
set prompt_time (date +%H:%M)
set prompt_timestamp $prompt_time
function record_duration --on-event fish_postexec
	set -g duration $CMD_DURATION
	set -g prompt_timestamp ''

	set -l current_time (date +%H:%M)
	if ! [ "$current_time" = "$prompt_time" ]
		set -g prompt_time $current_time
		set -g prompt_timestamp $current_time
	end
end

function fish_right_prompt
	if [ -n "$prompt_timestamp" ]
		printf "\e[2;37m%s" $prompt_timestamp
	else if [ -z "$old_fish" ] && [ "$duration" -gt 99 ]
		set_color white --dim
		set -l seconds (math --scale=2 "$duration / 1000")
		printf "+%ss" $seconds
	end
end

function fish_command_not_found
	if [ -e $DOTFILES/libexec/command-not-found ]
		$DOTFILES/libexec/command-not-found $argv
	else
		__fish_default_command_not_found_handler $argv
	end
end

if [ -z "$old_fish" ]
	if exists atuin
		source_init atuin init fish --disable-up-arrow
		or return
		bind -M default / _atuin_search
	end

	if exists zoxide
		source_init zoxide init fish
		or return
		function cd; z $argv; end
		complete --erase cd
		complete cd --wraps __zoxide_z
	end
end

if exists direnv
	source_init direnv hook fish
	or return
end

if isatty 0
	stty -ixon
end

if [ -x ~/.local/startup-hook ]
	~/.local/startup-hook
	set -l startup_status $status
	# `exit` in fish only exits the file, not the shell as a whole.
	[ $startup_status = 120 ]; and exec true
	return $startup_status
end
return 0
