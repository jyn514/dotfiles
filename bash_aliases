# don't judge me
alias serach='search'
alias stauts='status'

# sudo is necessary, don't ask
alias vpn='sudo openvpn --config /usr/local/etc/client.ovpn'
alias '?'='help'
alias weather='curl wttr.in'
alias status='git status'

# Add an "alert" alias for long running commands.  Use like so:
#   sleep 10; alert
alias alert='notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e '\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\'')"'

# https://stackoverflow.com/questions/9679932
alias npm-exec='npm bin'

alias make='make --warn-undefined-variables'
alias restart='shutdown -r now'
