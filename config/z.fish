function __z_arguments
	set -l curr_tok (builtin commandline --current-process --current-token --cut-at-cursor)
	__fish_complete_directories "$curr_tok" ""
	set -l results (command zoxide query --exclude (__zoxide_pwd) -l -- $curr_tok); or return
	printf '%s\n' $results | head -n20 | string replace $PWD/ "" | string replace $HOME "~"
end

complete -c __zoxide_z --no-files --keep-order -a '(__z_arguments)'
