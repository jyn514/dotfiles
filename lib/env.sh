# Note: this is a sh/fish polyglot,
# you must use `export` for all variables and cannot use command substitution.
# If you find yourself wanting that, put it in profile or config.fish.

export CARGO_HOME=~/.local/lib/cargo
export RUSTUP_HOME=~/.local/lib/rustup
export CARGO_TARGET_DIR=$CARGO_HOME/target
export CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
export STEEL_LSP_HOME=~/.config/helix/steel-lsp
export GOPATH=~/.local/lib/go
export GOBIN=$GOPATH/bin
export NVM_DIR=~/.local/lib/nvm
# less documents that it searches here by default, but the docs are wrong
export LESSKEYIN=~/.config/lesskey
# people keep passing random dumb arguments to less. override them so we use the defaults in lesskey.
export PAGER=less
export LESS=
export MANPAGER='nvim +Man! --clean -u ~/.config/nvim/alabaster.nvim/colors/alabaster-black.lua'
export DEBUGINFOD_URLS=https://debuginfod.ubuntu.com
export VISUAL=$EDITOR
# get ctrl+shift+u for unicode input to work in kitty
export GLFW_IM_MODULE=ibus
export ENV=~/.profile
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'
export ZDOTDIR=~/.config/zsh
export JUPYTER_CONFIG_DIR=~/.config/jupyter
export JAVA_HOME=/usr/lib/jvm/default-java
export BAT_TABS=8
export BAT_STYLE=changes,header,rule
export CARGO_MOMMYS_MOODS=ominous
export FZF_DEFAULT_OPTS='--cycle --exit-0 --select-1 --preview-window=wrap'
export MAKEFLAGS='-j4'
# for http://overthewire.org
# Honestly if you want to use this I don't really mind
export OTWUSERDIR=/d/SERPjdbrX3w3tsyXQQt0

# git treats `diff.external` extremely poorly; there's no way to unset it temporarily because `-c diff.external` tries to run an empty program.
# instead, set this through an external env variable so we can unset it with `env -u`.
# difft is super buggy though :( ignoring it for now
# export GIT_EXTERNAL_DIFF=difft
