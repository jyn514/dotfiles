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

function refresh-fish-cache
	set -l cache_arguments $argv
	set -l destination
	set -l dependencies
	set -l index 1
	while [ $index -le (count $argv) ]
		switch $argv[$index]
			case --destination
				set destination $argv[(math $index + 1)]
				set index (math $index + 1)
			case --dependency
				set --append dependencies $argv[(math $index + 1)]
				set index (math $index + 1)
			case --
				break
		end
		set index (math $index + 1)
	end
	if [ -f $destination ]
		set -l fresh 1
		for dependency in $dependencies
			if [ $dependency -nt $destination ]
				set fresh 0
				break
			end
		end
		if [ $fresh = 1 ]
			return 0
		end
	end
	command refresh-fish-cache $cache_arguments
end

if [ -f ~/.local/profile.fish ]
	. ~/.local/profile.fish
	or return
end

. $DOTFILES/lib/shell/env.sh; or return
. $DOTFILES/lib/shell/paths.sh; or return

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

set -l kernel (uname); or return
if [ "$kernel" = Linux ]; and [ -x /home/linuxbrew/.linuxbrew/bin/brew ]
	set -l brew_command /home/linuxbrew/.linuxbrew/bin/brew
	set -l brew_cache ~/.local/config/brew.fish
	refresh-fish-cache --destination $brew_cache --dependency $brew_command \
		-- $brew_command shellenv fish
	set -l brew_status $status
	contains $brew_status 0 75; or return $brew_status
	. $brew_cache; or return
end

if [ -z "$SSH_AUTH_SOCK" ]
	if [ "$kernel" = Darwin ]
		export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
	else
		export SSH_AUTH_SOCK=$HOME/.1password/agent.sock
	end
end

if exists mise
	set --erase MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH
	while set --local shim_index (contains --index -- "$HOME/.local/share/mise/shims" $PATH)
		set --erase PATH[$shim_index]
	end
	while set --local shim_index (contains --index -- "$HOME/.local/share/mise/shims" $fish_user_paths)
		set --erase fish_user_paths[$shim_index]
	end
	set --local clean_path
	for path_entry in $PATH
		contains -- $path_entry $clean_path; or set --append clean_path $path_entry
	end
	set --global --export PATH $clean_path
	set --erase clean_path path_entry shim_index
	if status --is-interactive
		source_init mise activate fish
	else
		source_init mise hook-env --shell fish --force
	end
	or return
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
	fzf --expect=tab,ctrl-o,ctrl-y,ctrl-l,alt-enter $argv
end

function fzf_action
	get_fzf_selection $argv | begin
		read --null key
		and read --null selection
	end
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
		set key Enter
	end
	set -l escaped_selection (string escape -- $selection)
	switch $key
		case Enter
			commandline -i $escaped_selection
			commandline -f execute
		case tab
			commandline -i $escaped_selection
		case ctrl-y
			printf '%s\0' "$selection" | picker-action copy --read0
		case ctrl-o
			commandline -r open
			commandline -i " $escaped_selection"
			commandline -f execute
		case alt-enter ctrl-l
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
	set -l fields (string split --max 1 = -- $alias)
	or return
	set -l name $fields[1]
	set -l value $fields[2]
	if [ $name = cat ]; continue; end
	abbr --add --global $name $value
	or return
end
set --erase abbreviations

abbr --add --global --command git -- -nv --no-verify

# load cargo aliases
if [ -z "$old_fish" ]; and exists cargo
	set -l cargo_alias_cache ~/.local/config/cargo.fish
	set -l cargo_command (command --search cargo)
	set -l cargo_abbr_command (command --search generate-cargo-fish-abbr)
		or return
	set -l cache_arguments --destination $cargo_alias_cache \
		--dependency $DOTFILES/config/config.fish \
		--dependency $cargo_command \
		--dependency $cargo_abbr_command
	if set -q CARGO_HOME; and [ -d $CARGO_HOME/bin ]
		set --append cache_arguments --dependency $CARGO_HOME/bin
	end
	refresh-fish-cache $cache_arguments -- $cargo_abbr_command $cargo_command
	set -l cargo_cache_status $status
	contains $cargo_cache_status 0 75; or return $cargo_cache_status
	. $cargo_alias_cache; or return
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

set -g fish_transient_prompt 1
set -e __dotfiles_previous_prompt_header
set -e __dotfiles_prompt_header
set -e __dotfiles_prompt_shows_header
set -e __dotfiles_prompt_status
set -e __dotfiles_previous_right_prompt
set -e __dotfiles_right_prompt
set -e __dotfiles_prompt_shows_right

function __dotfiles_render_prompt
	if [ "$__dotfiles_prompt_shows_header" = 1 ]
		printf '%s\n' "$__dotfiles_prompt_header"
	end
	if [ $__dotfiles_prompt_status -eq 0 ]
		printf '\e[0;32m; \e[0;0m'
	else
		printf '\e[0;31m; \e[0;0m'
	end
end

function fish_prompt
	set -l last_status $status
	if contains -- --final-rendering $argv
		__dotfiles_render_prompt
		return
	end

	set -l prompt_columns 0
	set -q COLUMNS; and set prompt_columns $COLUMNS
	set -l header (env COLUMNS=$prompt_columns \
		prompt-command fish-header $fish_name | string collect)
	set -l render_statuses $pipestatus
	if [ $render_statuses[1] -eq 0 ]; and [ $render_statuses[2] -eq 0 ]
		set -g __dotfiles_prompt_header $header
		if not set -q __dotfiles_previous_prompt_header; or \
			[ "$header" != "$__dotfiles_previous_prompt_header" ]
			set -g __dotfiles_prompt_shows_header 1
		else
			set -g __dotfiles_prompt_shows_header 0
		end
		set -g __dotfiles_previous_prompt_header $header
	else
		set -g __dotfiles_prompt_header ''
		set -g __dotfiles_prompt_shows_header 0
		set -e __dotfiles_previous_prompt_header
	end
	set -g __dotfiles_prompt_status $last_status
	__dotfiles_render_prompt
end

function fish_mode_prompt
end

function __dotfiles_render_mode
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
	if contains -- --final-rendering $argv
		if [ "$__dotfiles_prompt_shows_right" = 1 ]
			printf %s "$__dotfiles_right_prompt"
		end
		return
	end

	set -l rendered
	if [ -n "$prompt_timestamp" ]
		set rendered (printf '\e[2;37m⏱ %s' $prompt_timestamp)
	else if [ $duration -gt 99 ]
		set rendered (printf '\e[2;37m⏱ +%ss' (math --scale=2 "$duration / 1000"))
	end
	set -l mode (__dotfiles_render_mode | string collect)
	if [ -n "$mode" ]
		[ -n "$rendered" ]; and set --append rendered ' '
		set --append rendered $mode
	end
	set rendered (string join '' $rendered)
	set -g __dotfiles_right_prompt $rendered
	set -g __dotfiles_prompt_shows_right 0
	if [ -n "$rendered" ]
		if not set -q __dotfiles_previous_right_prompt; or \
			[ "$rendered" != "$__dotfiles_previous_right_prompt" ]
			set -g __dotfiles_prompt_shows_right 1
		end
	end
	set -g __dotfiles_previous_right_prompt $rendered
	if [ "$__dotfiles_prompt_shows_right" = 1 ]
		printf %s "$rendered"
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
	set -l startup_generator $DOTFILES/bin/generate-fish-startup-cache
	set -l startup_dependencies $startup_generator $DOTFILES/config/config.fish $DOTFILES/config/gitconfig
	set -l startup_commands
	set -l startup_availability
	for startup_command in bat git atuin zoxide direnv
		if set -l startup_path (command --search $startup_command)
			set --append startup_commands $startup_path
			set --append startup_dependencies $startup_path
			set --append startup_availability 1
		else
			set --append startup_commands -
			set --append startup_availability 0
		end
	end
	set -l startup_cache ~/.local/config/fish-startup-(string join '' $startup_availability).fish
	set -l startup_cache_arguments --destination $startup_cache
	for startup_dependency in $startup_dependencies
		set --append startup_cache_arguments --dependency $startup_dependency
	end
	refresh-fish-cache $startup_cache_arguments -- $startup_generator $startup_commands
	set -l startup_status $status
	contains $startup_status 0 75; or return $startup_status
	. $startup_cache; or return
	if [ $startup_availability[3] = 1 ]
		bind -M default / _atuin_search
	end
	if [ $startup_availability[4] = 1 ]
		function cd; z $argv; end
		complete --erase cd
		complete cd --wraps __zoxide_z
	end
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
