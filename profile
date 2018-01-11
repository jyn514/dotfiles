#     If not running interactively, don't do anything
[ -z "PS1" ] && return
case $- in
    *i*) ;;
      *) return;;
esac

[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

## Custom
umask 077

cdl () {
	cd "$@" && ls -CF
}

GITHUB='https://github.com/'
MY_GITHUB='https://github.com/jyn514'
SRC="/usr/local/src"

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

# bash shell and haven't sourced bashrc
if ps -p $$ -oargs= | grep bash > /dev/null && ! [ -v $BASH_PROFILE_READ ] ; then
	. ~/.bashrc
fi

# these look nice but are very slow
#GIT_PROMPT_ONLY_IN_REPO=1
#source /usr/local/src/bash-git-prompt/gitprompt.sh

