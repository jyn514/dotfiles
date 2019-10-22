# given a file using POSIX syntax, convert it to Fish syntax

# usage: sed -f this_file < bash_script > fish_script
# this is very hacky and comes with no guarantees that it will not break things

# my_func () { some commands; } -> function my_func; some commands; end
s#\s*\([a-zA-Z_][_a-zA-Z0-9]*\)\s*()\s*{\(.*\)}#function \1;\2end#

# my_func () { -> function my_func
s#\s*\([a-zA-Z_][_a-zA-Z0-9]*\)\s*()\s*{\s*#function \1#

# cd dir && ls -> cd dir; and ls
s#\(.*\)\s*&&\s*\(.*\)#\1; and \2#g

# do it three times in case multiple appear on one line
# TODO: rewrite this so it handles arbitrarily many &&
s#\(.*\)\s*&&\s*\(.*\)#\1; and \2#g
s#\(.*\)\s*&&\s*\(.*\)#\1; and \2#g

# same thing for ||
s#\(.*\)\s*||\s*\(.*\)#\1; or \2#g

# $(command_sub) -> (command_sub)
s#\("\?\)\$\(([^)]*)\)\1#\2#g
# multiple times in case substitutions appear within one another
# TODO: ditto
s#\$\(([^)]*)\)#\1#g
s#\$\(([^)]*)\)#\1#g

# replace "\033[0;31m" with "\033\[0;31m"
s#"\([^"]*\)\[\([^"]*\)"#"\1\\[\2"#g

# replace fi with end
s#\(^\|\s\)\(esac\|fi\|done\|}\)\($\|\s\)#\1end\3#
# replace { with begin
s#\(^\|\s\){\($\|\s\)#\1begin\2#

# replace special variables
s/"\$@"/$argv/g
s/\$#/(count $argv)/g
s/\$?/$status/g

# replace variable assignment
# exports. NOTE: fish's 'export' function is buggy, so we do it manually
s/\(\s*\)export\s\+\([a-zA-Z_][_a-zA-Z0-9]*\)\s*=\(\S*\)/\1set -gx \2 \3/
# local
s/\(\s*\)local\s\+\([a-zA-Z_][_a-zA-Z0-9]*\)\s*=\(\S*\)/\1local \2 \3/
# regular
s/\(\s*\)\([a-zA-Z_][_a-zA-Z0-9]*\)\s*=\(\S*\)/\1set \2 \3/

# replace ${RED} with "$RED"
s/\${\([a-zA-Z_][_a-zA-Z0-9]*\)}/"$\1"/g

# replace if command; then with if comment
s/; then\($\|\s\)/\1/g
s/\s*then\($\|\s\)/ /g

# ! -> not
s/!\(\s*\)/not\1/g
