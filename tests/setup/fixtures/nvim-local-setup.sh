# Keep package installation offline while exercising the real local setup path.
install_glide_native() { return 0; }
install_dragon_native() { return 0; }
install_mise() { return 0; }
install_pi() { return 0; }
install_platform_bundles() { return 0; }
setup_python() { return 0; }
exists() { [ "$1" = nvim ]; }

python3() {
	case "$1" in
		libexec/setup/glide.py) return 0;;
		libexec/setup/install_bootstrap.py)
			[ "$2" = clone ] && [ "$3" = lazy.nvim ] || return 90
			printf '%s\n' "$4" >> "$NVIM_SETUP_CLONES"
			[ "$NVIM_SETUP_CLONE_STATUS" = 0 ] || return "$NVIM_SETUP_CLONE_STATUS"
			mkdir -p "$4/lua/lazy" || return
			printf '%s\n' 'return {}' > "$4/lua/lazy/init.lua"
			;;
		*) return 91;;
	esac
}

nvim() {
	case " $* " in
		*' --clean '*) printf '%s' "$XDG_DATA_HOME/nvim";;
		*)
			[ -f "$XDG_DATA_HOME/nvim/lazy/lazy.nvim/lua/lazy/init.lua" ] || return 92
			printf '%s\n' startup >> "$NVIM_SETUP_STARTS"
			return "$NVIM_SETUP_START_STATUS"
			;;
	esac
}
