set -l curr_tok    (builtin commandline --current-process --current-token --cut-at-cursor)

function __z_arguments
	__fish_complete_directories "$curr_tok" ""
	command zoxide query --exclude (__zoxide_pwd) -l -- $curr_tok \
		| head -n20 | string replace $PWD/ "" | string replace $HOME "~"
end

complete -c __zoxide_z --no-files --keep-order -a '(__z_arguments)'
