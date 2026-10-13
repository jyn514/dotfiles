exists() { return 1; }
history_calls=0
zle() {
	if [[ $1 == up-line-or-history ]]; then
		(( history_calls += 1 ))
		BUFFER='previous command'
		LBUFFER=$BUFFER
	fi
}
source "$PROFILE_ZSH" || exit
BUFFER='current command'
LBUFFER='current '
zle-sudo
[[ $LBUFFER == 'sudo current ' && $history_calls == 0 ]] || exit 41
BUFFER=''
LBUFFER=''
zle-sudo
[[ $LBUFFER == 'sudo previous command' && $history_calls == 1 ]] || exit 42
