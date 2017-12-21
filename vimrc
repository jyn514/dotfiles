nmap <Enter> o<Esc>

" mostly copied from https://github.com/charlesdaniels/dotfiles/blob/master/provision/overlay/.vimrc
" Thanks, Charles!
set backspace=indent,eol,start " fix dumbass default backspace behavior
set nowrap                     " disable line wrapping
" enable a nice interactive menu for tab-completing buffers and such
set wildmenu
set wildmode=longest:full,full

syntax on
set number
set ignorecase "for searching"
set ruler
set ffs=unix,dos

""""""""10""""""""20""""""""3 platform detection 0""""""""60""""""""70""""""""80

let g:uname = substitute(system("uname"), '\n\+$', '', '')

" platform will be POSIX, NT, or UNKNOWN
" variant refers to the flavor, such as POSIX/Linux, or POSIX/BSD

let g:platform = "UNKNOWN"
let g:variant = "UNKNOWN"

if (has("win32") || has("win64"))
	let g:platform = "NT"
	let g:variant = "NT"
endif

if g:uname =~ "FreeBSD"
	let g:platform = "POSIX"
	let g:variant = "BSD"
endif

if g:uname =~ "Linux"
	let g:platform = "POSIX"
	let g:platform = "LINUX"
endif

if g:uname =~ "MINGW"
	let g:platform = "POSIX"
	let g:variant = "MINGW"
endif

if g:uname =~ "Darwin"
	let g:platform = "POSIX"
	let g:variant = "MACOS"
endif

""""""""10""""""""20""""""""3 shell configuration """"""""60""""""""70""""""""80

set shell=/bin/sh

if g:platform == "NT"
	set shell=C:\Windows\system32\cmd.exe
endif

""""""""10""""""""20""""""""30" UTF-8 handling "50""""""""60""""""""70""""""""80

let g:multibytesupport = "NO"
if has("multi_byte") || has ("multi_byte_ime/dyn")
	let g:multibytesupport = "YES"
endif

if g:multibytesupport == "YES"
	" we can only enable utf-8 if we have multi byte support compiled in
	scriptencoding utf-8
	set encoding=utf-8
	set fileencoding=utf-8
	set fileencodings=ucs-bom,utf8,prc
	set langmenu=en_US.UTF-8
endif

" show non-printing characters

set list
set listchars=
set listchars+=trail:¬
set listchars+=precedes:«
set listchars+=extends:»
set listchars+=tab:>-


""""""""10""""""""20"""""""" indentation settings """"""""60""""""""70""""""""80

function TwoSpacesSoftTabs()
	set tabstop=2
	set shiftwidth=2
	set softtabstop=2
	set expandtab
endfunction

function EightSpacesHardTabs()
	set tabstop=8
	set shiftwidth=8
	set softtabstop=8
	set noexpandtab
endfunction

function FourSpacesSoftTabs()
	set tabstop=4
	set shiftwidth=4
	set softtabstop=4
	set expandtab
endfunction

function FourSpacesHardTabs()
	set tabstop=4
	set shiftwidth=4
	set softtabstop=4
	set noexpandtab
endfunction

" use "normal" tabs n spaces by default
call EightSpacesHardTabs()

""""""""10""""""""20""""""" filetype configuration """""""60""""""""70""""""""80

" forcibly use the c filetype for all header files
autocmd BufNewFile,BufRead *.h,*.c set filetype=c

" use tex filetype for *.tex
autocmd BufNewFile,BufRead *.tex,*.sty set filetype=tex

" Handle YAML files correctly
autocmd BufNewFile,BufRead *.yml,*.yaml,Sakefile set filetype=yaml

" fix broken behaviour for CHANGELOG files
autocmd BufEnter CHANGELOG setlocal filetype=text

" set up tab & space behaviour sensibly
autocmd FileType c call EightSpacesHardTabs()
autocmd FileType java call FourSpacesSoftTabs()
autocmd FileType python call FourSpacesSoftTabs()
autocmd FileType tex call EightSpacesHardTabs()
autocmd FileType yaml call FourSpacesSoftTabs()
autocmd FileType sh call EightSpacesHardTabs()
autocmd FileType perl call EightSpacesHardTabs()
autocmd FileType html call TwoSpacesSoftTabs()

