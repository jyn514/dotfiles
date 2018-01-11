alias serach='search' # don't judge me
# sudo is necessary, don't ask
alias vpn='sudo openvpn --config /usr/local/etc/client.ovpn'
alias '?'='help'
alias weather='curl wttr.in'
alias status='git status'
# Add an "alert" alias for long running commands.  Use like so:
#   sleep 10; alert
alias alert='notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e '\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\'')"'
