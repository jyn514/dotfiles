function __zoxide_pwd
	pwd
end
source "$PROFILE_Z"
complete --do-complete '__zoxide_z first' >/dev/null
complete --do-complete '__zoxide_z second' >/dev/null
