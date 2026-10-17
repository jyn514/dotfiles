# Agent availability must not block shell startup, including over a dead tunnel.
function select-local-ssh-agent
	if test -n "$SSH_AUTH_SOCK"
		return 0
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
	set -gx SSH_AUTH_SOCK "$agent"
end

select-local-ssh-agent
functions -e select-local-ssh-agent
