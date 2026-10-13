# Preserve reachable agents, including agents with no keys (ssh-add exits 1).
function select-local-ssh-agent
	if test -n "$SSH_AUTH_SOCK"
		command ssh-add -l >/dev/null 2>&1
		test $status -eq 2; or return 0
	end

	if test -n "$TMUX"
		# SSH_CONNECTION in a persistent pane describes its original attachment.
		command python3 "$DOTFILES/libexec/tmux/local-client.py"; or return 0
	else if test -n "$SSH_CONNECTION"; or test -n "$SSH_TTY"; or test -n "$SSH_CLIENT"
		return 0
	end

	set -l agent "$HOME/.1password/agent.sock"
	set -l kernel (command uname); or return 0
	if test "$kernel" = Darwin
		set agent "$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
	end
	command env SSH_AUTH_SOCK="$agent" ssh-add -l >/dev/null 2>&1
	if contains $status 0 1
		set -gx SSH_AUTH_SOCK "$agent"
	end
end

select-local-ssh-agent
functions -e select-local-ssh-agent
