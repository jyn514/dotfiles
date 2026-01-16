# Note: this is a sh/fish polyglot,
# you must use `export` for all variables and cannot use command substitution.
# If you find yourself wanting that, put it in profile or config.fish.

# XDG settings, see https://wiki.archlinux.org/title/XDG_Base_Directory
# TODO: make this work for vim, see https://tlvince.com/vim-respect-xdg
# will be non-trivial because nvim also reads VIMINIT: https://neovim.io/doc/user/starting.html
export XDG_CONFIG_HOME=$HOME/.config
export INPUTRC=$XDG_CONFIG_HOME/readline/inputrc
export STEEL_LSP_HOME=$HOME/.config/helix/steel-lsp
# less documents that it searches here by default, but the docs are wrong
export LESSKEYIN=$HOME/.config/lesskey
export ZDOTDIR=$HOME/.config/zsh
export JUPYTER_CONFIG_DIR=$HOME/.config/jupyter
# otherwise it uses /Library/Application Support on macOS :/
export BACON_PREFS=$HOME/.config/bacon/prefs.toml

export CARGO_HOME=$HOME/.local/lib/cargo
export RUSTUP_HOME=$HOME/.local/lib/rustup
export GOPATH=$HOME/.local/lib/go
export GOBIN=$GOPATH/bin
export NVM_DIR=$HOME/.local/lib/nvm

export CARGO_TARGET_DIR=$HOME/.cache/cargo

# misc config
export CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
export DEBUGINFOD_URLS=https://debuginfod.ubuntu.com
# get ctrl+shift+u for unicode input to work in kitty
export GLFW_IM_MODULE=ibus
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'
export CARGO_MOMMYS_MOODS=ominous
export FZF_DEFAULT_OPTS='--cycle --exit-0 --select-1 --preview-window=wrap'
export MAKEFLAGS='-j'
export BAT_TABS=8
export BAT_STYLE=changes,header,rule

# behavior changes

export MANPAGER='nvim +Man! --clean -u $HOME/.local/share/nvim/lazy/alabaster.nvim/colors/alabaster-black.lua'

# set up dumb posix shells correctly
export ENV=$HOME/.profile

# people keep passing random dumb arguments to less. override them so we use the defaults in lesskey.
export PAGER=less
export LESS=

# for http://overthewire.org
# Honestly if you want to use this I don't really mind
export OTWUSERDIR=/d/SERPjdbrX3w3tsyXQQt0

# git treats `diff.external` extremely poorly; there's no way to unset it temporarily because `-c diff.external` tries to run an empty program.
# instead, set this through an external env variable so we can unset it with `env -u`.
# difft is super buggy though :( ignoring it for now
# export GIT_EXTERNAL_DIFF=difft
