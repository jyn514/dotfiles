declare -r BASH_PROFILE_READ
if [ -z $MY_GITHUB ]; then
	source ~/.profile
fi
shopt -s histappend
shopt -s checkwinsize
shopt -s globstar
shopt -s checkhash
# enable` color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors)"
    alias ls='ls --color=always'
    alias dir='dir --color=always'
    alias vdir='vdir --color=always'
    alias grep='grep --color=always'
    alias shellcheck='shellcheck --color=always'
    alias less='less -R'
fi

# colored GCC warnings and errors
export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'

# some more ls aliases
alias ll='ls -g'
alias la='ls -A'
alias l='ls -CF'

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
   debian_chroot=$(cat /etc/debian_chroot)
fi

## History ##
# don't put duplicate lines in the history.
HISTCONTROL=ignoredups

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=200
# non-numeric means no truncation
HISTFILESIZE=no_delete
#############

if [ -x /usr/bin/tput ] && tput setaf 1 >/dev/null 2>&1; then
    PS1="${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]$ "
else
    PS1="${debian_chroot:+($debian_chroot)}\u@\h:\w\$ "
fi
unset color_prompt

# use command-not-found package if installed
if [ -x /usr/lib/command-not-found -o -x /usr/share/command-not-found/command-not-found ]; then
        function command_not_found_handle {
                # check because c-n-f could've been removed in the meantime
                if [ -x /usr/lib/command-not-found ]; then
                   /usr/lib/command-not-found -- "$1"
                   return $?
                elif [ -x /usr/share/command-not-found/command-not-found ]; then
                   /usr/share/command-not-found/command-not-found -- "$1"
                   return $?
                else
                   printf "%s: command not found\n" "$1" >&2
                   return 127
                fi
        }
fi

export NVM_DIR="~/.local/lib/nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

# custom (2017-10-22)
function which_branch {
	# ask for ref from git, discarding all errors
	ref="$(cd $PWD && git symbolic-ref HEAD 2> /dev/null)" || return
	# get only the last file of $ref
	echo "(${ref#refs/heads/})"
	unset ref
}

alert () {
        notify-send --urgency=low \
        "$([ $? = 0 ] && echo terminal || echo error)" \
        "$(history | tail -1 | sed -e 's/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//')"
}

if [ -f ~/.config/exercism/exercism_completion.bash ]; then
	. ~/.config/exercism/exercism_completion.bash
fi

# enable programmable completion features
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

# today in history
calendar -l 0
