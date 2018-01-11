#     If not running interactively, don't do anything
[ -z "PS1" ] && return
case $- in
    *i*) ;;
      *) return;;
esac

## History ##
# don't put duplicate lines in the history.
HISTCONTROL=ignoreups

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=200
# anything non-numeric means no truncation
HISTFILESIZE=no_delete
#############

### shell options ###
# append to the history file, don't overwrite it
shopt -s histappend

# check the window size after each command
shopt -s checkwinsize

# If set, the pattern "**" used in a pathname expansion context will
# match all files and zero or more directories and subdirectories.
shopt -s globstar

# Make sure hashed programs exist before executing them
shopt -s checkhash
##############

# make `less` more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

case "$TERM" in
    xterm-color|*-256color) color_prompt=yes;;
esac

if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
# We have color support; assume it's compliant with Ecma-48
# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
# a case would tend to support setf rather than setaf.)
	color_prompt=yes
else
	color_prompt=
fi

# custom (2017-10-22)
#function which_branch {
	# ask for ref from git, discarding all errors
#	ref="$(cd $PWD && git symbolic-ref HEAD 2> /dev/null)" || return
	# get only the last file of $ref
#	echo "(${ref#refs/heads/})"
#	unset ref
#}

if [ "$color_prompt" = yes ]; then
    PS1="${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "
else
    PS1="${debian_chroot:+($debian_chroot)}\u@\h:\w\$ "
fi
unset color_prompt

# enable color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
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
alias ll='ls -l'
alias la='ls -A'
alias l='ls -CF'

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# if the command-not-found package is installed, use it
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

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

## Custom
umask 077
# today in history
calendar -l 0

function updateWebsite {
	current=`pwd`
	website=`find ~ -name first-website -type d`
	echo Updating website...
	cd $website && git pull
	cd $current
	unset current
}

cdl () {
	cd "$@" && ls -CF
}

GITHUB='https://github.com/'
MY_GITHUB='https://github.com/jyn514'
SRC="/usr/local/src"

if [ -f ~/.config/exercism/exercism_completion.bash ]; then
	. ~/.config/exercism/exercism_completion.bash
fi

if [ -f ~/.local/profile ]; then
	. ~/.local/profile
fi

if [ -d ~/.local/bin ]; then
	PATH="$HOME/.local/bin:$PATH"
fi

export MANPAGER=most
export GEM_HOME=~/.local/lib/gem/ruby/2.3.0
export GEM_PATH="$GEM_HOME:/var/lib/ruby/gems/1.8"
PATH="$PATH:$GEM_HOME/bin"
export EDITOR=emacs
export VISUAL=emacs
export JUPYTER_CONFIG_DIR=~/.config/jupyter
export JAVA_HOME=/usr/lib/jvm/default-java
# parallel even when invoked by a script
export MAKEFLAGS='-j4'
# only when invoked by interactive shell
MAKEFLAGS+=' --warn-undefined-variables'

# for http://overthewire.org
# Honestly if you want to use this I don't really mind
export OTWUSERDIR="/d/SERPjdbrX3w3tsyXQQt0"

# these look nice but are very slow
#GIT_PROMPT_ONLY_IN_REPO=1
#source /usr/local/src/bash-git-prompt/gitprompt.sh
