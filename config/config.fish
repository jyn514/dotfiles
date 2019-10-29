if [ -x /usr/bin/lesspipe ]
	eval (set SHELL /bin/sh lesspipe)
end

## Custom
umask 077

# don't add path if already present
function add_path
	# (start or ':') $1 (end or ':')
	if not echo "$PATH" | grep "\(^\|:\)$1\(\$\|:\)" > /dev/null
		set PATH "$1:$PATH"
	end
end

function open; xdg-open $argv; end

function yts; youtube_search $argv; end

function ytd; youtube-dl $argv; end

function cls; clear; end

function mkcd; mkdir -p $argv ; and cd "$1"; end
function mkdc; mkcd $argv; end

# follow symlinks by default
function rg; command rg -L $argv; end

# show human-readable dates with offsets by default
function dmesg; command dmesg -e $argv; end

function dkr; docker $argv; end
function dkrc; docker-compose $argv; end
# this shadows a mailcap command, but I've never used mailcap in my life
function compose; docker-compose $argv; end

function what_belongs
	if command -v dpkg > /dev/null
		dpkg -L $argv
	elif command -v rpm > /dev/null
		rpm -ql $argv
	else
		echo "no supported package manager found" >&2
	end
end

function what_runs
	for file in (what_belongs $argv); do
		[ -f "$file" ] ; and \[ -x "$file" ] ; and echo "$file"
	end
end

function what_package
	set prog (realpath "$1"); shift
	if command -v dpkg > /dev/null
		dpkg -S (command -v "$prog") $argv
	elif command -v rpm > /dev/null
		rpm -qf (command -v "$prog") $argv
	else
		echo "no supported package manager found" >&2
	end
end

function belongs; what_belongs $argv; end
function runs; what_runs $argv; end
function package; what_package $argv; end

function exa; command exa --git $argv; end

# don't replace crontab without warning
function crontab; command crontab -i $argv; end

# show a makefile as a dependency graph
function visualize
	command -v makefile2graph > /dev/null ; or begin echo "makefile2graph not found"; return 1; end
	command -v dot > /dev/null ; or begin echo "dot not found"; return 1; end
	command -v xdot > /dev/null ; or begin echo "xdot not found"; return 1; end
	makefile2graph | dot | xdot /dev/stdin
end

# don't show copyright every time (super annoying)
function gdb; command gdb -q $argv; end

# for use with a makefile in the current directory
function tasks
	make -npRr | \
	awk -v set RS  -F: '/^# File/,/^# Finished Make data base/ {if ($$1 not~ "^\[#.]") {print $$1}}' | \
	grep -v "^\[#(printf '\t')]" | sed 's/:.*$//'
end

# same as tasks, but show body of recipe
function recipies
	make -npRr | \
	awk -v set RS  -F: '/^# File/,/^# Finished Make data base/ {if ($$1 not~ "^\[#.]") {print $$1}}' | \
	grep -v "^#"
end

# launch and disown a command
function background
	if [ (count $argv) -eq 0 ]
 echo usage: background '<command>'
		return 1
	else
		$argv &
		disown
	end
end

function show_time; watch -n 1 -t date; end

# zip recursively by default
function zip; command zip -r $argv; end

function powershell; pwsh $argv; end

function save_power; sudo powertop --auto-tune; end

function clean_shell
    env -i set HOME "$HOME" TERM="$TERM" (command -v bash) --noprofile --rcfile /etc/profile
end

if ls --set color auto >/dev/null 2>/dev/null
function ls; command ls --set color auto $argv; end
else
function ls; command ls -G $argv; end
end

# prompt before removing
function rm; command rm -i $argv; end

function purge_removed
	dpkg -l | awk '/^rc/ {print $2}' | xargs sudo dpkg --purge
end

function purge; sudo apt autoremove --purge $argv; end

function restart; shutdown -r now; end

function sl; ls; end

function ll; ls -l $argv; end

function la; ls -A $argv; end

function l; ls -F $argv; end

function webpaste
   nc termbin.com 9999 < $argv
end

function webpaste
   nc termbin.com 9999 < $argv
end

function ascii; man ascii; end

# files on disk
function file_count; locate -S; end

function excuse
	telnet towel.blinkenlights.nl 666 2>/dev/null | tail -2 | cowsay -f dragon
end

function dad; curl https://icanhazdadjoke.com ; and echo; end

function weather; curl wttr.in/~University+Of+South+Carolina; end
function wttr; weather; end

function pytime; python -m timeit; end

function ubuntu; docker run -it ubuntu; end

function vpn; sudo openvpn --config /usr/local/etc/client.ovpn; end

function view_markdown
	markdown_py -x extra "$1" > tmp.html ; and firefox tmp.html ; and sleep 1 ; and rm -f tmp.html
end

function pip_upgrade_all
	pip list | awk '{print $1}' | tail --set lines +3 | xargs pip install -U $argv
end

#   sleep 10; alert
function alert
	notify-send --set urgency low \
	([ $set status  0 ] ; and echo terminal ; or echo error) \
	(history | tail -1 | sed -e 's/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//')
end

# https://stackoverflow.com/questions/9679932
function npm_exec
	set COMMAND "npm bin"
	if [ (count $argv) -gt 0 ] ; and [ "$1" = "-g" ]
 set COMMAND "$COMMAND --global"
		shift
	end
	set PATH "($COMMAND):$PATH" $argv;
end

# modified from https://github.com/charlesdaniels/dotfiles/blob/master/overlay/.zsh/zsh-ocd.zsh
# when run without arguments, print all directories where there's an open file handle
# for the programs listed in FILTER_REGEX (currently bash and vim)
# when run with arguments,
#  if there is a unique match for the argument as a extended regex, change to that directory
#  else, print all directories which did match
function ocd
	set OCD_BLACKLIST_REGEX '(^[/]lib)|(^[/]usr[/]lib)|(^[/]$)|(^[/]var)|(^[/]bin)|(^[/]usr[/]share)|(^[/]usr[/]bin)|(^[/]usr[/]local[/]bin)|(^[/]tmp)|(^[/]dev)|(share[/]fonts)|([/][.]cache[/])|([.]swp$)|(^[/]run)'
	set OCD_FILTER_REGEX '(^(ba|z)?sh)|(^[gn]?vim)'
	set OCD_FILE_LIST ""

	if [ -x (command -v lsof 2>/dev/null) ] 
		set OCD_FILE_LIST "(lsof -u (whoami) | grep -E $OCD_FILTER_REGEX | awk '{print($9);}' | grep -P '^\[/]' | grep -P -v $OCD_BLACKLIST_REGEX | sort | uniq)"
	end

	# make sure everything in the file list is a directory
	set OCD_DIRLIST ""
	for ocd_fpath in (echo $OCD_FILE_LIST | tr '\n' ' ') ; do
		if [ -f "$ocd_fpath" ] 
			set ocd_fpath (dirname "$ocd_fpath")
		end
		set OCD_DIRLIST "$ocd_fpath
$OCD_DIRLIST"
	end

	set OCD_TARGET (echo "$OCD_DIRLIST" | sort | uniq | grep -v -P '^$' | grep -P "$1")
	if [ (echo "$OCD_TARGET" | wc -l) -eq 1 ] 
		cd "$OCD_TARGET"
	else
		echo "$OCD_TARGET"
	end
end


set GITHUB 'https://github.com/'
set MY_GITHUB 'https://github.com/jyn514'
set SRC "/usr/local/src"

if [ -f ~/.local/profile ]
end

if [ -d ~/.local/bin ]
	add_path "$HOME/.local/bin"
end

set -gx ENV "$HOME/.profile"
set -gx GEM_HOME ~/.local/lib/gem/ruby/2.3.0
set -gx GEM_PATH "$GEM_HOME:/var/lib/ruby/gems/1.8"
add_path "$GEM_HOME/bin"
set -gx EDITOR vim
set -gx VISUAL vim
set -gx GCC_COLORS 'set error 01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'
set -gx JUPYTER_CONFIG_DIR ~/.config/jupyter
set -gx JAVA_HOME /usr/lib/jvm/default-java
set -gx BAT_TABS 8

set -gx MAKEFLAGS '-j4'
# for http://overthewire.org
# Honestly if you want to use this I don't really mind
set -gx OTWUSERDIR "/d/SERPjdbrX3w3tsyXQQt0"

# bash shell and haven't sourced bashrc
# -p excludes parent processes (cygwin has habit of running 'bash' forking)
if [ "$BASH_VERSION" ] ; and not \[ -v "$BASH_PROFILE_READ" ]
end

export HAVE_BROKEN_WCWIDTH 0

function fish_prompt
  printf '('
  set_color yellow
  printf fish
  set_color normal
  [ (id -u) -eq 0 ]; and begin
    printf ,
    set_color red
    printf root
    set_color normal
  end
  printf ") "
  set_color blue
  printf '%s' (prompt_pwd)
  set_color normal
  echo " > "
end

add_path (dirname "(dirname "(realpath ~/.profile))")/bin"
add_path ~/.node/bin
add_path ~/.cargo/bin
stty -ixon
l
