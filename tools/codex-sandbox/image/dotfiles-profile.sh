#!/bin/sh

# Noninteractive dotfile behavior shared with agent sandboxes. Keep startup
# deterministic: no prompts, credential discovery, host services, or tool hooks.
export DOTFILES_SANDBOX=1
export XDG_CONFIG_HOME=$HOME/.config
export CARGO_HOME=$HOME/.local/lib/cargo
export RUSTUP_HOME=$HOME/.local/lib/rustup
export GOPATH=$HOME/.local/lib/go
export GOBIN=$GOPATH/bin
export CARGO_TARGET_DIR=$HOME/.cache/cargo
export CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
export MAKEFLAGS=-j4
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'
export EDITOR=vi
export VISUAL=$EDITOR
export PAGER=cat
export GIT_PAGER=cat

for directory in /opt/agent-pi/bin /opt/agent-tools/bin /libexec/agent-wrappers; do
	case ":$PATH:" in
		*:$directory:*) ;;
		*) PATH=$directory:$PATH ;;
	esac
done
unset directory
export PATH
