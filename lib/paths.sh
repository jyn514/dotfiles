# Note: this is a sh/fish polyglot.
# Unlike env.sh, it's source in non-interactive shells.

add_path_if_present /opt/nvim/bin
add_path_if_present ~/.local/lib/node_modules/bin
add_path "$GOBIN"
add_path "$CARGO_HOME"/bin

# add this even if it's not present, in case we create it later
add_path "$HOME/.local/bin"
add_path "$DOTFILES/bin"
