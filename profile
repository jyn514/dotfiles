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

purge_removed () {
	dpkg -l | awk '/^rc/ {print $2}' | xargs sudo dpkg --purge
}

status () {
	git status
}

dad () {
	curl https://icanhazdadjoke.com
	echo
}

weather () {
	curl wttr.in
}

pytime () {
	python -m timeit
}

alert () {
	notify-send --urgency=low \
	"$([ $? = 0 ] && echo terminal || echo error)" \
	"$(history | tail -1 | sed -e 's/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//')"
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

export ENV="$HOME/.profile"
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
MAKEFLAGS="$MAKEFLAGS --warn-undefined-variables"

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

