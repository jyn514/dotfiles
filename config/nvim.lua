---@diagnostic disable: lowercase-global
---@diagnostic disable: missing-fields
---
-- skeleton comes from https://github.com/nvim-lua/kickstart.nvim/blob/5bdde24dfb353d365d908c5dd700f412ed2ffb17/init.lua
-- use `:verbose set foo` to see where option `foo` is set
-- use `:verbose map foo` to see where keybind `foo` is set
-- use `vim --startuptime vim.log +qall; cat vim.log` to profile startup
-- use `:lua =SOMETABLE` to pretty print it
-- use `<C-k>` in insert mode to debug what keys are called (use <C-k>\ to bypass tmux)
-- alternatively, <C-v>

local first_run = not vim.g.lazy_did_setup

---- Options ----

-- misc
vim.g.mapleader = ' '
vim.g.maplocalleader = 'f'
vim.opt.undofile = true
vim.opt.ignorecase = true
vim.opt.wildignorecase = true
vim.opt.smartcase = true
vim.opt.scrolloff = 3
vim.opt.sidescrolloff = 10
vim.opt.visualbell = true
vim.opt.title = true  -- allows M-d to search for a file
-- see `:help zo` for keybinds
vim.opt.shiftround = true      -- TODO: disable this for markdown and mumps files

-- folds
vim.opt.foldlevelstart = 4
vim.opt.foldminlines = 2
vim.opt.foldmethod = "expr"
vim.opt.foldexpr = "v:lua.vim.lsp.foldexpr()"

-- ui
vim.opt.termguicolors = true
vim.opt.number = true
vim.opt.breakindent = true
vim.opt.list = true
vim.opt.listchars = { tab = '│ ', trail = '·', nbsp = '␣' }
-- shows :s/foo/bar preview live
vim.opt.inccommand = 'split'

-- TODO: OSC 52 (`:h clipboard-osc52`)
vim.cmd.set('clipboard=unnamed')

-- disable some warnings
vim.g.loaded_node_provider = 0
vim.g.loaded_perl_provider = 0
vim.g.loaded_ruby_provider = 0

-- use absolute directions for search, not relative
vim.keymap.set('n', 'n', '/<CR>')
vim.keymap.set('n', 'N', '?<CR>')

-- If this doesn't look right, try `:set termguicolors`.
-- SSH should be forwarding $COLORTERM, which sets it automatically, but some ssh servers block it unless you add `AcceptEnv COLORTERM`.
---- Autocommands ----

vim.api.nvim_create_autocmd('TextYankPost', {
	desc = 'Highlight when copying text',
	callback = function() vim.hl.on_yank() end,
})

vim.api.nvim_create_autocmd('VimResized', {
	desc = 'Automatically equalize windows on terminal size change',
	command = 'wincmd ='
})

---- Filetype options ----

function indentgroup(lang, func)
	local group = vim.api.nvim_create_augroup(lang..'indent', {})
	vim.api.nvim_create_autocmd('FileType', {
		group = group,
		callback = function(event)
			if event.match == lang then
				func()
			end
		end
	})
end
-- only use this with `:lua`; otherwise use ~/.editorconfig
function hard_tabs(count)
	vim.bo.expandtab = false
	vim.bo.tabstop = count
	vim.bo.softtabstop = count
	vim.bo.shiftwidth = count
end
function spaces(count, global)
	if global then
		opt = vim.opt
	else
		opt = vim.bo
	end
	opt.expandtab = true
	opt.tabstop = 8
	opt.softtabstop = count
	opt.shiftwidth = count
end
function length(count)
	vim.wo.colorcolumn = tostring(count)
	vim.bo.textwidth = count
end
indent_tab = hard_tabs
indent_space = spaces

indentgroup('c', function()
	length(132)
end)
-- c gets confused for cpp all the time 🥲
indentgroup('cpp', function()
	length(132)
end)
indentgroup('csh', function()
	length(132)
end)
-- llvm uses 2 spaces and llvm is the only c++ codebase i care about
-- indentgroup('cpp', function() spaces(2) end)

vim.opt.colorcolumn = "92"
vim.opt.textwidth = 92

---- Keybinds ----

vim.keymap.set('n', '<Esc>', function()
	-- If we find a floating window, close it.
	-- https://www.reddit.com/r/neovim/comments/11axh2p/comment/jasdwkr/?utm_source=share&utm_medium=web3x&utm_name=web3xcss&utm_term=1&utm_content=share_button
	local found_float = false
	for _, win in ipairs(vim.api.nvim_list_wins()) do
		if vim.api.nvim_win_get_config(win).relative ~= '' then
			vim.api.nvim_win_close(win, true)
			found_float = true
		end
	end

	if found_float then
		return
	end

	vim.cmd.nohlsearch()
end)

-- what does this do lol
-- vim.keymap.set('n', '<leader>q', vim.diagnostic.setloclist, { desc = 'Open diagnostic [Q]uickfix list' })
--
function bind(binding, target, desc)
	vim.keymap.set({'n', 'v'}, binding, target, { desc = desc })
end

vim.keymap.set('n', '<A-h>', '<C-w><C-h>', { desc = 'Move focus to the left window' })
vim.keymap.set('n', '<A-l>', '<C-w><C-l>', { desc = 'Move focus to the right window' })
vim.keymap.set('n', '<A-j>', '<C-w><C-j>', { desc = 'Move focus to the lower window' })
vim.keymap.set('n', '<A-k>', '<C-w><C-k>', { desc = 'Move focus to the upper window' })
vim.keymap.set('n', '<A-z>', '<C-w>_', { desc = 'Maximize the current window' })

vim.keymap.set('n', 'gqq', 'gww', { desc = 'Only format selection, not sentence' })

-- TODO: these don't work in visual mode
bind('<A-Left>', '<C-o>', 'Go back in history')
bind('<A-Right>', '<C-i>', 'Go forward in history')
bind('<X1Mouse>', '<C-o>', 'Go back in history')
bind('<X2Mouse>', '<C-i>', 'Go forward in history')

vim.keymap.set('n', '<A-i>', 'i_<Esc>r', { desc = 'Insert a single character' })

vim.keymap.set('', '<S-ScrollWheelDown>', '5zl', { desc = 'Scroll right' })
vim.keymap.set('', '<S-ScrollWheelUp>', '5zh', { desc = 'Scroll left' })
vim.keymap.set('', '<A-ScrollWheelDown>', '<C-d>', { desc = 'Scroll page up' })
vim.keymap.set('', '<A-ScrollWheelUp>', '<C-u>', { desc = 'Scroll page down' })

-- to insert newline without indentation, use `[ `

vim.keymap.set('n', '<leader>t', function()
	vim.cmd.wall()
	vim.cmd.make('test')
end, { desc = "Run `make test`" })
-- TODO: add ninja output to `errorformat` (see `:h efm-ignore`)

-- add some emacs keybinds
vim.keymap.set({'i', 'c'}, '<C-e>', '<End>', { desc = "End" }) -- overwrites "insert character on line below" with no replacement
vim.keymap.set({'i', 'c'}, '<C-a>', '<Home>', { desc = "Home" }) -- overwrites "insert previously inserted text" with no replacement

-- add some helix keybinds
vim.keymap.set('n', 'U', '<C-r>', { desc = "Redo" }) -- overwrites "undo line" with no replacement
vim.keymap.set('n', 'ga', ':b#<cr>', { desc = "Go to most recently used buffer" }) -- overwrites `:as[cii]` keybind
vim.keymap.set('n', 'gn', ':bnext<cr>', { desc = "Go to next buffer" }) -- overwrites `nv` keybind
vim.keymap.set('n', 'gp', ':bprevious<cr>', { desc = "Go to previous buffer" }) -- overwrites "paste before cursor"

-- note: overwrites select mode
vim.keymap.set({'n', 'v'}, 'gh', '^', { desc = "Go to line start" })
vim.keymap.set({'n', 'v'}, 'gl', '$', { desc = "Go to line end" })

-- for flower
vim.keymap.set('i', '<M-f>', '◊', { desc = "Lozenge" })
vim.keymap.set('i', '\\f', '◊', { desc = "Lozenge" })
vim.keymap.set('i', '\\j', '«', { desc = "Sunflower open quote" })
vim.keymap.set('i', '\\k', '»', { desc = "Sunflower close quote" })

-- https://vi.stackexchange.com/a/43848
vim.keymap.set('i', '<Tab>', function()
	local col = vim.fn.getcurpos()[3] - 1  -- convert 1-indexed to 0-indexed
	local ws = vim.regex('^\\s*$')
	-- TODO: figure out how to do this with match_line
	local line = vim.fn.getline('.'):sub(0, col)
	if ws:match_str(line) then
		return '<Tab>'
	else
		local sw = vim.fn.shiftwidth()
		local width = sw - ((col-1) % sw)
		return vim.fn['repeat'](' ', width)
	end
end, { expr = true, desc = "Don't insert hard tabs in the middle of lines" })

-- completion
vim.keymap.set('i', '<C-n>', '<C-x><C-o>', { desc = "Trigger omnicompletion" }) -- overwrites "complete keyword"
vim.keymap.set('i', '<C-c>', function()
	return vim.fn.pumvisible() and '<C-e>' or '<C-c>'
end, { expr = true, desc = "Cancel completion" }) -- overwrites "return to normal mode immediately"

vim.keymap.set('n', 'g>', function()
	vim.cmd('enew')
	vim.cmd("put = execute('messages')")
end, {desc = "View message history in a new searchable buffer"})

---- Commands ----

local config = vim.fn.stdpath("config") .. '/init.lua'
vim.api.nvim_create_user_command('EditConfig', 'edit '..config, { desc = "edit Lua config" })
vim.api.nvim_create_user_command('ReloadConfig', 'source '..config, { desc = "reload Lua config" })
vim.api.nvim_create_user_command('TrimWhitespace', function(info)
	local view = vim.fn.winsaveview()
	local cmd = 'keeppatterns '
	if info.range > 0 then
		cmd = cmd..info.line1..','..info.line2
	end
	vim.cmd(cmd..[[s/\s\+$//e]])
	vim.fn.winrestview(view)
end, { range = true, desc = "trim trailing spaces" })

function BufferDelete(args)
	if args.bang then
		vim.cmd 'bdelete!'
	else
		vim.cmd.bdelete()
	end
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		if vim.api.nvim_buf_is_loaded(buf) and buf ~= vim.api.nvim_get_current_buf() then
			vim.cmd('let @# = '..buf)
			break
		end
	end
	-- NOTE: does nothing if there is only one buffer open, i.e. `ga` will still go to the most recently closed buffer
end
vim.api.nvim_create_user_command('BufferDelete', BufferDelete,
	{ bang = true, desc = "like :bdelete but also updates the alternate file" })

-- Show all highlights
vim.api.nvim_create_user_command('ShowHighlights', function()
	vim.cmd('source $VIMRUNTIME/syntax/hitest.vim')
end, {desc = "Show a list of all highlight groups"})

-- autosave on cursor hold
local timers = {}
function autosave_enable()
	local buf = vim.api.nvim_get_current_buf()
	if timers[buf] then
		return
	end

	local buf_name = vim.fn.expand '%'
	vim.notify("autosaving "..buf_name)
	timers[buf] = vim.api.nvim_create_autocmd("CursorHold", {
		desc = "Save "..buf_name.." on change",
		callback = function()
			vim.api.nvim_buf_call(buf, function() vim.cmd "silent update" end)
	end })
end
vim.api.nvim_create_user_command('AutoSave', autosave_enable, {desc = "Start saving each second on change"})

function autosave_disable()
	local buf = vim.api.nvim_get_current_buf()
	local cmd = timers[buf]
	if cmd then
		vim.api.nvim_del_autocmd(cmd)
		timers[buf] = nil
	end
end
vim.api.nvim_create_user_command('AutoSaveDisable', autosave_disable, {desc = "Stop autosaving"})

-- abbreviations
-- https://vi.stackexchange.com/a/33221, plus hackery to only match at the start
function abbrev(lhs, rhs)
	vim.keymap.set('ca', lhs, function()
		if vim.fn.getcmdtype() == ':' and string.find(vim.fn.getcmdline(), "^%s*"..lhs.."%s*$") then
			return rhs
		else
			return lhs
		end
	end, { expr = true })
end
abbrev('Q', 'quit')
abbrev('open', 'edit')
abbrev('o', 'edit')
abbrev('W', 'w')
abbrev('bc', 'BufferDelete')
abbrev('bc!', 'BufferDelete!')
abbrev('rm', 'Remove')
abbrev('mv', 'Rename')
abbrev('ec', 'EditConfig')
abbrev('Ec', 'EditConfig')
abbrev('as', 'AutoSave')
abbrev('health', 'checkhealth')
abbrev('lsp', 'LspInfo')
abbrev('tt', 'TrimWhitespace')

---- Plugins ----

-- Bootstrap lazy.nvim
if first_run then
	local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
	vim.opt.rtp:prepend(lazypath)

	require("lazy").setup({
		{ "folke/neoconf.nvim", cmd = "Neoconf", config = true },
		{ "folke/lazydev.nvim", ft = "lua", opts = {
			-- See the configuration section for more details
			-- Load luvit types when the `vim.uv` word is found
			library = { { path = "${3rd}/luv/library", words = { "vim%.uv" } } },
		} },
		'tpope/vim-obsession',  -- session save/resume
		'numToStr/Comment.nvim',
		-- general picker
		{ "ibhagwan/fzf-lua",
			dependencies = { 'nvim-mini/mini.icons' }},
		-- removes deprecation warnings
		{ 'kosayoda/nvim-lightbulb', commit = 'ffddd221ed561c2cca8b94e0608379033c5aa562' },
		'echasnovski/mini.nvim',    -- toolbar, also icons
		"folke/which-key.nvim",     -- spawns kak/hx-like popup
		'lewis6991/gitsigns.nvim',  -- also does inline blame
		'tpope/vim-eunuch',  -- file operations
		{'tpope/vim-fugitive', -- open url of commit under cursor
			dependencies = { "tpope/vim-rhubarb" }},
		{ "chrisgrieser/nvim-spider", lazy = true },  -- partial word movement
		{ 'vxpm/rust-expand-macro.nvim', lazy = true, ft = "rust", config = function()
			local expand_macro = require('rust-expand-macro').expand_macro
			vim.api.nvim_create_user_command('ExpandMacro', expand_macro,
				{desc = "Expand macro recursively"})
		end},
		'neovim/nvim-lspconfig',
		{ 'jyn514/alabaster.nvim', branch = 'dark' },
		'mfussenegger/nvim-dap',    -- debugging
		{ "rcarriga/nvim-dap-ui", dependencies = {"nvim-neotest/nvim-nio"} },
		{ "saghen/blink.cmp",
			dependencies = { "rafamadriz/friendly-snippets" }},
		{'nvim-treesitter/nvim-treesitter',
			build = ':TSUpdate',
			branch = "master",
			dependencies = { 'nvim-treesitter/nvim-treesitter-textobjects', branch = 'main' }},
		'HiPhish/rainbow-delimiters.nvim',
		{ "julienvincent/nvim-paredit" },
		{ "kylechui/nvim-surround", version = "^3.0.0" },
		{ "folke/snacks.nvim", priority = 1000, opts = {
			image = { enabled = true, }
		} },
		{ 'brenoprata10/nvim-highlight-colors', opts = {} },
		{ "MeanderingProgrammer/render-markdown.nvim", ft = "markdown", opts = {
			html = { comment = { conceal = false } },
			render_modes = {'n', 'v', 'i', 'c', 't', 'x' },
			code = { border = 'thin' },
		}},
		{ "chenxin-yan/footnote.nvim", ft = "markdown", opts = {} },
		{ 'ymich9963/mdnotes.nvim',
			commit = 'bfdcd7e1e91ec1d9b380507182c2fd7c783f5641',
			ft = "markdown",
			opts = {
				auto_list_renumber = false,
				assets_path = "assets",
			},
		},
		{ "michaelb/sniprun", branch = "master", lazy = true, opts = {
			selected_interpreters = { "Lua_nvim" },
			repl_enable = { "Clojure_fifo" },
		}},
		--https://github.com/smoka7/hop.nvim  -- random access within file

		-- not going to bother setting this up until
		-- https://github.com/neovim/neovim/issues/24690 is fixed
		--https://github.com/amitds1997/remote-nvim.nvim
	}, { install = { missing = true }, rocks = { enabled = false } })
end

-- https://gitlab.com/HiPhish/rainbow-delimiters.nvim/-/issues/23
-- vim.g.rainbow_delimiters.query.rust = 'at-least-one-param'
_ = [[
	(parameters
  "(" @delimiter
  (parameter)+
  ")" @delimiter @sentinel) @container
]]

require('nvim-surround').setup {}

function set_spider(keybind, motion, desc)
	vim.keymap.set(
	{ "n", "o", "x" },
	keybind,
	"<cmd>lua require('spider').motion('"..motion.."')<CR>",
	{ desc = desc }
	)
end
set_spider('H', 'b', 'Move to previous sub word')
set_spider('L', 'w', 'Move to next sub word start')
-- set_spider('<A-l>', 'e', 'Move to next sub word end')

bind('<leader><Enter>', function()
	require('sniprun')
	vim.cmd('SnipRun')
end, 'Run code block on current line')

paredit = require 'nvim-paredit'
paredit.setup {
	indent = { enabled = true },
	dragging = { auto_drag_pairs = false },
	keys = {
		["<leader>@"] = { paredit.unwrap.unwrap_form_under_cursor, "Splice sexp" },
		["<leader>o"] = { paredit.api.raise_form, "Raise form" },
		["<leader>O"] = { paredit.api.raise_element, "Raise element" },

		['se'] = { paredit.api.drag_element_forwards, "Drag element right" },
		['sE'] = { paredit.api.drag_element_backwards, "Drag element left" },
		['sp'] = { paredit.api.drag_pair_forwards, "Drag element pairs right" },
		['sP'] = { paredit.api.drag_pair_backwards, "Drag element pairs left" },
		['sf'] = { paredit.api.drag_form_forwards, "Drag form right" },
		['sF'] = { paredit.api.drag_form_backwards, "Drag form left" },
		["s)"] = { paredit.api.slurp_forwards, "Slurp forwards" },
		["s("] = { paredit.api.barf_backwards, "Barf backwards" },
		["S)"] = { paredit.api.barf_forwards, "Barf forwards" },
		["S("] = { paredit.api.slurp_backwards, "Slurp backwards" },
		['B'] = false,
		['E'] = false,
		['W'] = false,
		['('] = {
			paredit.api.move_to_prev_element_head,
			"Jump to previous element head",
			repeatable = false,
			mode = { "n", 'x', 'o', 'v' },
		},
		[')'] = {
			paredit.api.move_to_next_element_tail,
			"Jump to next element tail",
			repeatable = false,
			mode = { "n", 'x', 'o', 'v' },
		},
		["{"] = {
			paredit.api.move_to_parent_form_start,
			"Jump to parent form's head",
			repeatable = false,
			mode = { "n", "x", 'o', "v" },
		},
		["}"] = {
			paredit.api.move_to_parent_form_end,
			"Jump to parent form's tail",
			repeatable = false,
			mode = { "n", "x", 'o', "v" },
		},
		['gE'] = false,
		["gb"] = {
			paredit.api.move_to_prev_element_tail,
			"Jump to previous element tail",
			repeatable = false,
			mode = { "n", "x", "o", "v" },
		},
		["gw"] = {
			paredit.api.move_to_next_element_head,
			"Jump to next element head",
			repeatable = false,
			mode = { "n", "x", "o", "v" },
		},
		['T'] = false,
		['gF'] = {
			paredit.api.move_to_top_level_form_head,
			"Jump to top level form's head",
			repeatable = false,
			mode = { "n", "x", 'o', "v" },
		},
	}
}

require('blink.cmp').setup {
	cmdline = {
		completion = {
			menu = { auto_show = true, },
		},
		keymap = {
			['<Left>'] = false,
			['<Right>'] = false,
			['<C-f>'] = { 'select_and_accept', 'fallback' },
			['<C-y>'] = { 'accept_and_enter', 'fallback' },
			['<C-Enter>'] = { 'accept_and_enter', 'fallback' },
		},
	},
	completion = {
		keyword = { range = 'full' },
		list = { selection = { preselect = false } },
		menu = { auto_show = true, },
	},
	fuzzy = { implementation = "lua" },
	-- See https://github.com/rafamadriz/friendly-snippets/tree/main/snippets for a list of
	-- snippets
	keymap = {
		['<C-f>'] = { 'select_and_accept', 'fallback' },
		['<Enter>'] = { 'snippet_forward', 'fallback' },
		['<C-e>'] = { 'cancel', 'hide_signature', 'fallback' },
		['<C-n>'] = { 'show', 'select_next', 'fallback' },
	},
	signature = {
		enabled = true,
		window = { show_documentation = false, }
	},
	sources = {
		-- this breaks horribly :(
		--default = { 'lsp', 'omni', 'snippets', 'path', 'buffer' },
	},
}

-- hm, maybe https://github.com/Saecki/crates.nvim/wiki/Documentation-v0.7.1 ?
-- ok actually wtf lol https://github.com/mrcjkb/rustaceanvim?tab=readme-ov-file#books-usage--features
-- https://github.com/jmbuhr/otter.nvim looks based as hell omg
-- https://github.com/hrsh7th/cmp-path seems good
-- https://github.com/petertriho/cmp-git looks nice, but i thought gitsigns did that already?
-- hm, could do https://github.com/ray-x/cmp-treesitter instead of 'buffer'. or https://github.com/hrsh7th/cmp-nvim-lsp-document-symbol

---- Treesitter ---

local function ts(binds)
	selections = {}
	swaps = {
		swap_next = {},
		swap_previous = {},
	}
	moves = {
		goto_next_start = {},
		goto_next_end = {},
		goto_previous_start = {},
		goto_previous_end = {},
	}
	for bind, query in pairs(binds) do
		if type(query) ~= 'table' then
			query = { capture = query, group = 'textobjects' }
		end
		local inner = vim.deepcopy(query)
		local outer = vim.deepcopy(query)
		inner.kind = 'inner'
		outer.kind = 'outer'
		upper = string.upper(bind)
		if upper == bind then
			if bind == ';' then
				upper = ':'
			elseif bind == '=' then
				upper = '+'
			else
				error("don't know how to bind moves for"..bind)
			end
		end

		selections['a'..bind] = outer
		selections['i'..bind] = inner
		swaps.swap_next['s'..bind] = inner
		swaps.swap_previous['s'..upper] = inner
		swaps.swap_next['S'..bind] = outer
		swaps.swap_previous['S'..upper] = outer
		moves.goto_next_start[']'..bind] = outer
		moves.goto_next_end[']'..upper] = outer
		moves.goto_previous_start['['..bind] = outer
		moves.goto_previous_end['['..upper] = outer
	end
	return { selections = selections, swaps = swaps, moves = moves }
end

function bind_ts(capture_associations)
	local select = require 'nvim-treesitter-textobjects.select'
	local swap = require 'nvim-treesitter-textobjects.swap'
	local move = require 'nvim-treesitter-textobjects.move'

	local swaps = capture_associations.swaps or {}
	local moves = capture_associations.moves or {}

	local meta = {
		["Select"] = {
			bindings = capture_associations.selections or {},
			func = select.select_textobject,
			modes = {'x', 'o'},
		},
		["Swap next"] = {
			bindings = swaps.swap_next,
			func = swap.swap_next,
			modes = 'n',
		},
		["Swap previous"] = {
			bindings = swaps.swap_previous,
			func = swap.swap_previous,
			modes = 'n',
		},
		["Next start"] = {
			bindings = moves.goto_next_start,
			func = move.goto_next_start,
			modes = {'n', 'x', 'o'},
		},
		["Next end"] = {
		bindings = moves.goto_next_end,
		func = move.goto_next_end,
		modes = {'n', 'x', 'o'},
		},
		["Previous start"] = {
			bindings = moves.goto_previous_start,
			func = move.goto_previous_start,
			modes = {'n', 'x', 'o'},
		},
		["Previous end"] = {
			bindings = moves.goto_previous_end,
			func = move.goto_previous_end,
			modes = {'n', 'x', 'o'},
		},
	}

	for desc, spec in pairs(meta) do
		for binding, query in pairs(spec.bindings) do
			local name, group
			if type(query) ~= 'table' then
				name = query
				group = 'textobjects'
			else
				group = query.group
				if group == 'textobjects' and not query.no_suffix then
					name = '@'..query.capture..'.'..query.kind
				else
					name = '@'..query.capture
				end
			end
			vim.keymap.set(spec.modes, binding, function()
				spec.func(name, group)
			end, {desc = desc..' '..name})
		end
	end

end


require('nvim-treesitter.configs').setup {
	auto_install = true,
	highlight = { enable = true },
	-- incremental_selection = { enable = true },
}

require('nvim-treesitter-textobjects').setup {
	select = { lookahead = true, },
	move = { set_jumps = true },
}

-- https://github.com/nvim-treesitter/nvim-treesitter-textobjects#built-in-textobjects
local captures = ts {
	f = 'function',
	c = 'call',
	l = 'loop',
	r = 'return',
	['='] = 'assignment',
	p = 'parameter',
	i = 'conditional', -- mnemonic: "If"
	h = 'statement', -- mnemonic: "left of line" (same as 'h' in normal mode)
	[';'] = 'comment',
	b = 'block',
	x = 'regex',
	k = "class",
	-- https://github.com/nvim-treesitter/nvim-treesitter/blob/main/queries/lua/locals.scm
	s = { capture = 'local.scope', group = 'locals' },
	v = { capture = 'local.definition.var', group = 'locals' },
	z = { capture = 'fold', group = 'folds' },
}
captures.swaps.swap_previous["<A-k>"] = "@parameter.inner"
captures.swaps.swap_next["<A-j>"] = "@parameter.inner"
captures.swaps.swap_previous["<A-Up>"] = "@statement.outer"
captures.swaps.swap_next["<A-Down>"] = "@statement.outer"
captures.selections["in"] = "@number.inner"
captures.moves.goto_next_start["]n"] = "@number.inner"
captures.moves.goto_previous_start["[n"] = "@number.inner"

--captures.swaps.swap_next["<leader>p"] = "@parameter.inner"
--captures.swaps.swap_previous["<leader>P"] = "@parameter.inner"

bind_ts(captures)

local ts_repeat_move = require "nvim-treesitter-textobjects.repeatable_move"
vim.keymap.set({ "n", "x", "o" }, ";", ts_repeat_move.repeat_last_move_next)
vim.keymap.set({ "n", "x", "o" }, ",", ts_repeat_move.repeat_last_move_previous)

---- Comments ----

require('Comment').setup {
	mappings = {
		basic = false,
		extra = false,
	}
}
local ft_comment = require 'Comment.ft'
ft_comment.set('dl', ft_comment.get('c'))
ft_comment.set('flix', ft_comment.get('c'))
ft_comment.set('rhombus', ft_comment.get('c'))

comment_api = require 'Comment.api'
vim.keymap.set({'n', 'i'}, '<C-_>', comment_api.toggle.linewise.current, {desc = "Toggle comment"})
vim.keymap.set('n', '<C-c>', comment_api.toggle.linewise.current, {desc = "Toggle comment"})
-- TODO: find a way to only comment out the selected region
-- using blockwise comments doesn't work in all filetypes
vim.keymap.set('v', '<C-_>', '<Plug>(comment_toggle_linewise_visual)')
vim.keymap.set('v', '<C-c>', '<Plug>(comment_toggle_linewise_visual)')

vim.api.nvim_create_user_command('MoveCommentUp', function(info)
	local view = vim.fn.winsaveview()

	local comment = vim.bo.commentstring
	if comment == "" then return end
	comment = string.gsub(comment, "%%s", "")

	-- TODO: need to escape regex metacharacters
	-- {-} means "non-greedy *"
	local regex = [[s/\(\s*\)\(.\{-}\) \?\(]]..comment..[[.*\)/\1\3\r\1\2/e]]
	for line = info.line2, info.line1, -1 do
		if string.find(vim.fn.getline(line), comment, 1, true) then
			vim.cmd('keeppatterns '..line..regex)
		end
	end

	vim.fn.winrestview(view)
end, { range = true, desc = "Move comment to line above" })

bind('gqk', ":MoveCommentUp<CR>", 'Move comment to line above')

---- Pickers ----

local pickers = require 'fzf-lua'
if first_run then
	pickers.register_ui_select()
end

pickers.setup {
	defaults = {
		file_icons = "mini",
		-- breaks horribly on rust :(
		-- https://github.com/ibhagwan/fzf-lua/issues/2392#issuecomment-3418641875
		--path_shorten = 2,
		winopts = { preview = { winopts = {
			wrap = true,
			-- https://github.com/ibhagwan/fzf-lua/issues/2518#issuecomment-3764040980
			--tabstop = 2,
		}}},
	},
	files = {
		-- file_icons = false,
		rg_opts = [[-g "!src/llvm-project" -g "!src/tools/rustc-perf"]],
		fd_opts = [[--no-hidden --exclude src/llvm-project --exclude src/tools/rustc-perf]],
	},
	git = {
		files = {
			git_icons = false,
			cmd = "git ls-files --modified --exclude-standard --directory $(git rev-parse --show-toplevel)",
		}
	},
	oldfiles = {
		include_current_session = true,
		-- stat_file = false,  -- startup times
	}
}

-- vim.keymap.set('i', '<tab>', function() pickers.complete_path() end)

vim.keymap.set('n', '<leader>b', function()
	pickers.buffers({
		winopts = {title="Buffers"},
	})
end, { desc = "Open buffer picker" })

vim.keymap.set('n', '<leader>f', function()
	local cwd = vim.fs.root(0, { "Cargo.toml", ".git" }) or vim.fn.expand('%:p:h')
	local is_git_dir = vim.system({'git', 'rev-parse', '--is-inside-work-tree'},
		{text = true, cwd = cwd}):wait().code == 0
	local files
	if is_git_dir then
		files = "git_files;oldfiles;files"
	else
		files = "oldfiles;files"
	end
	pickers.combine({
		pickers = files,
		winopts = {title="Files"},
		cwd = cwd,
	})
end, { desc = "Open '''smart''' fuzzy file picker" })

vim.keymap.set('n', '<leader><C-f>', function()
	pickers.files({ path_shorten = 2, winopts = {title="All tracked files"}})
end, { desc = "Open file picker (all files in current directory)" })

vim.keymap.set('n', '<leader><A-f>', function()
	pickers.files({ no_ignore = true, no_ignore_parent = true, hidden = true })
end, { desc = "Open file picker (include ignored)" })

vim.keymap.set('n', '<leader>F', pickers.history, { desc = "Open file picker (all files ever opened)" })

vim.keymap.set('n', '<leader>/', function()
	pickers.grep()
end, { desc = "Search in working dir" })
	-- pickers.live_grep({prompt_title = "Live Search"})

vim.keymap.set('n', '<leader><C-_>', function()
	pickers.grep({cwd = vim.fs.root(0, { "Cargo.toml", ".git" }) })
end, { desc = "Search current package or workspace" })

vim.keymap.set('n', '<leader>g', function()
	pickers.git_files({
		prompt = "Modified Files",
	})
end, { desc = "Modified files" })
bind('<leader>k', pickers.keymaps, 'Show all active keybindings')
bind('<leader>u', pickers.undotree, 'Show edit history')
bind('<leader>m', pickers.marks, 'Show marks')
bind('<leader>z', pickers.zoxide, 'Jump to directory')

bind('gqd', function()
	local word = vim.fn.expand("<cword>")
	pickers.live_grep({
		search = '('
			.. [[(providers|queries|hooks)\.]]..word..' ='
			..'|^\\s*'..word..'(,|: [a-z_:,]+$)'
			..'|Providers .*'..word
			..')',
		cwd = 'compiler',
		no_esc = true,
		rg_opts = '--case-sensitive -g "!rustc_span/src/symbol.rs"'
			..' --column --no-heading --line-number --color=always --max-columns=4096',
	})
end, 'Goto rustc_query definition')

require("nvim-lightbulb").setup({
	autocmd = { enabled = true }
})

---- UI ----

vim.cmd.colorscheme 'alabaster-black'

-- try Meslo on macOS; look for "use different font for non-ascii glyphs" in iTerm settings
require('mini.icons').setup {
	-- style = 'ascii',
}
MiniStatusline = require'mini.statusline'
MiniStatusline.setup {
	content = {
		active = function()
			local git           = MiniStatusline.section_git({ trunc_width = 40 })
			local diff          = MiniStatusline.section_diff({ trunc_width = 75 })
			local diagnostics   = MiniStatusline.section_diagnostics({ trunc_width = 75 })
			local lsp           = MiniStatusline.section_lsp({ trunc_width = 75 })
			-- always use relative filepath, to make it easier to notice when editing a file not in the LSP workspace
			local filename      = '%f%m%r'
			local fileinfo      = MiniStatusline.section_fileinfo({ trunc_width = 120 })

			local pos = vim.fn.getcurpos()
			local location = pos[2]..':'..pos[3]
			local session = vim.fn.ObsessionStatus('⏵', '⏸')

			return MiniStatusline.combine_groups({
				{ hl = 'Normal', strings = { filename } },
				{ hl = 'Conceal',  strings = { git, diff, diagnostics, lsp, session } },
				'%<', -- Mark general truncate point
				'%=', -- End left alignment
				{ hl = 'Conceal', strings = { fileinfo, location } },
			})
		end
	}
}
if first_run then
	wk = require('which-key')
	wk.setup({preset = 'helix', delay = 150, icons = {mappings = false},
		triggers = {
			{ "<auto>", mode = "nixsotc" },
			-- { "<auto>", mode = "nxso" },
			{ "<localleader>", mode = {'n', 'v'} },
			-- override default 's' binding so we see swaps sooner
			{ "s", mode = {'n'}},
		}
	})
	wk.add({
		{ '<LocalLeader>', group = "Debugging" },
		{ '[', group = "Previous object" },
		{ ']', group = "Next object" },
	})
end

require('rainbow-delimiters.setup') {
	highlight = {
		'RainbowDelimiterYellow',
		'RainbowDelimiterOrange',
		'RainbowDelimiterViolet',
		'Label',
		'RainbowDelimiterGreen',
	},
}

local gitsigns = require('gitsigns')
gitsigns.setup({
	current_line_blame = true,
	signs = {
		add = { text = '+' },
		change = { text = '~' },
		delete = { text = '_' },
		topdelete = { text = '‾' },
		changedelete = { text = '~' },
	}
})

bind('<leader>h', gitsigns.blame_line, 'Show blame for current line ([h]istory)')
bind('<leader>o', ":'<,'>GBrowse<CR>", "open commit under cursor")

---- Debugging ----

local dap = require('dap')
dap.adapters.cppdbg = {
  id = 'cppdbg',
  type = 'executable',
	-- https://github.com/mfussenegger/nvim-dap/wiki/C-C---Rust-(gdb-via--vscode-cpptools)#installation
  command = '/home/jyn/.local/lib/cpptools/extension/debugAdapters/bin/OpenDebugAD7'
}
-- TODO: get rr integration working
-- https://github.com/farre/midas/ looks promising
-- see also https://github.com/rr-debugger/rr/wiki/Using-rr-in-an-IDE#setting-up-visual-studio-code
dap.configurations.cpp = {
	-- See https://code.visualstudio.com/docs/cpp/launch-json-reference
  {
    name = "Launch file",
    type = "cppdbg",
    request = "launch",
		program = vim.fn.getcwd() .. '/build/yottadb',
		args = {"-run", "naked"},
    cwd = '${workspaceFolder}',
    stopAtEntry = false,
		cwd = vim.fn.getcwd(),
    -- program = function()
      -- return vim.fn.input('Path to executable: ', vim.fn.getcwd() .. '/', 'file')
    -- end,
  },
}
dap.configurations.c = dap.configurations.cpp
dap.configurations.rust = dap.configurations.cpp

local dap_widgets = require('dap.ui.widgets')
local dapui = require('dapui')
bind('<LocalLeader>b', dap.toggle_breakpoint, 'Toggle line breakpoint')
bind('<LocalLeader>c', dap.continue, 'Start or continue running')
bind('<LocalLeader>C', dap.reverse_continue, 'Reverse-continue')
bind('<LocalLeader>r', dap.restart, 'Restart debuggee')
bind('<LocalLeader>g', dap.run_to_cursor, 'Run to current line') --mnemonic: goto
-- TODO: this doesn't work without an attached session :(
-- bind('<LocalLeader><LocalLeader>', dap.run_to_cursor, 'Run to current line') --mnemonic: double-tap
bind('<LocalLeader><Up>', dap.up, 'Go up frame')
bind('<LocalLeader><Down>', dap.down, 'Go down frame')
-- by analogy with ctrl-o,ctrl-i
-- mnemonic: out, in
bind('<LocalLeader>o', dap.up, 'Go up frame')
bind('<LocalLeader>i', dap.down, 'Go down frame')
bind('<LocalLeader>z', dap.focus_frame, 'Focus current frame')
bind('<LocalLeader>j', dap.step_into, 'Step into')
bind('<LocalLeader>k', dap.step_out, 'Step out')  -- i think this is what gdb calls 'finish'?
bind('<LocalLeader>l', dap.step_over, 'Step over')
bind('<LocalLeader>h', dap.step_back, 'Step backwards')
-- K by analogy with normal hover
bind('<LocalLeader>K', dap_widgets.hover, 'Inspect expression')
bind('<LocalLeader><Esc>', function() dap.terminate() dapui.close() end, 'Kill process and stop debug session')
-- NOTE: you can set up `display` equivalent by entering insert mode in the 'DAP Watches' panel,
-- but this is NOT the same as a hardware watchpoint.
-- For the latter use `-exec watch ...`
-- See https://github.com/mfussenegger/nvim-dap/issues/1452.
-- TODO: set up a keybinding for watchpoints
-- TODO: set up a thread picker with telescope.
-- might also be useful to replace stack trace on the left?
-- see https://github.com/nvim-telescope/telescope-vimspector.nvim/blob/master/lua/telescope/_extensions/vimspector.lua for a simple example

dapui.setup()
dap.listeners.before.attach.dapui_config = dapui.open
dap.listeners.before.launch.dapui_config = dapui.open
-- this is so broken lmao, let's not even try
-- dap.listeners.after.launch.record = function()
-- 	dap.repl.execute("-exec target record-full")
-- end
dap.listeners.before.event_terminated.dapui_config = dapui.close
dap.listeners.before.event_exited.dapui_config = dapui.close

---- LSP ----

require('vim.lsp.log').set_format_func(vim.inspect)
vim.diagnostic.config({ underline = true })

-- Delete some built-in bindings that conflict.
for _, k in ipairs({'grr', 'grn', 'grt', 'gri', 'gra', 'gcc'}) do
	vim.cmd('silent! nunmap '..k)
end

vim.keymap.set('n', 'gd', '<C-]>', { desc = "Goto definition" })
vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, { desc = "Goto declaration" })
vim.keymap.set('n', 'gr', pickers.lsp_references, { desc = "Find references" })
vim.keymap.set('n', 'gy', pickers.lsp_typedefs, { desc = "Goto type definition" })
vim.keymap.set('n', 'gi', pickers.lsp_implementations, { desc = "Goto type implementation" })
vim.keymap.set('n', '<leader>.', vim.lsp.buf.code_action, { desc = "LSP code action" })
vim.keymap.set('n', '<leader>r', vim.lsp.buf.rename, { desc = "Rename symbol" })
vim.keymap.set('n', '<leader>s', pickers.lsp_document_symbols, { desc = "Show symbols in the current buffer" })
vim.keymap.set('n', '<leader>S', pickers.lsp_workspace_symbols, { desc = "Show all symbols in the workspace" })
vim.keymap.set('n', '<leader>q', pickers.quickfix, { desc = "Show quickfixes" })
vim.keymap.set('n', '<leader>d', pickers.lsp_document_diagnostics, { desc = "Show workspace diagnostics (errors)" })
vim.keymap.set('n', '<leader>D', pickers.lsp_workspace_diagnostics, { desc = "Show workspace diagnostics (all)" })
vim.keymap.set('n', '<leader>e', vim.diagnostic.open_float, { desc = "Show details for errors on the current line" })
vim.keymap.set({'n','v'}, 'g=', vim.lsp.buf.format, { desc = "Format whole file" })

-- only really supported by the rust LSP
vim.keymap.set('n', 'gc', pickers.lsp_incoming_calls, { desc = "Show incoming calls" })
vim.keymap.set('n', 'gC', pickers.lsp_outgoing_calls, { desc = "Show outgoing calls" })

vim.api.nvim_create_autocmd("User", {
	pattern = "TelescopePreviewerLoaded",
	-- make previews show less space and more text
	callback = function(args)
		vim.wo.wrap = true
		vim.cmd.normal("zs")
		vim.bo.tabstop = 2
	end,
})

-- use K for hover

-- from `:h lspattach` and https://sbulav.github.io/til/til-neovim-highlight-references/
vim.api.nvim_create_autocmd("LspAttach", { callback = function(args)
	local bufnr = args.buf
	local client = vim.lsp.get_client_by_id(args.data.client_id)
	if not client then return end
	-- Server capabilities spec:
	-- https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#serverCapabilities
	if client.server_capabilities.documentHighlightProvider then
		vim.api.nvim_create_augroup("lsp_document_highlight", { clear = true })
		vim.api.nvim_clear_autocmds { buffer = bufnr, group = "lsp_document_highlight" }
		vim.api.nvim_create_autocmd({"CursorHold", "CursorHoldI"}, {
			callback = vim.lsp.buf.document_highlight,
			buffer = bufnr,
			group = "lsp_document_highlight",
			desc = "Document Highlight",
		})
		vim.api.nvim_create_autocmd("CursorMoved", {
			callback = vim.lsp.buf.clear_references,
			buffer = bufnr,
			group = "lsp_document_highlight",
			desc = "Clear All the References",
		})
	end
	if client.server_capabilities.codeLensProvider then
		vim.keymap.set('n', '<leader>L', vim.lsp.codelens.run, { desc = "Run codelens" })
		-- TODO: should be CursorHold, but that causes flickering
		-- TODO: why doesn't LspAttach work
		-- https://github.com/neovim/neovim/issues/34965
		vim.api.nvim_create_autocmd({ "BufEnter", "LspAttach" }, {
			callback = function() vim.lsp.codelens.refresh { bufnr = 0 } end,
			buffer = bufnr,
			desc = "Refresh codelens actions",
		})
	end
end })

if vim.fn.has('nvim-0.11') == 1 then
	vim.api.nvim_create_autocmd('LspNotify', {
		callback = function(args)
			if args.data.method == 'textDocument/didOpen' then
				vim.lsp.foldclose('imports', vim.fn.bufwinid(args.buf))
			end
		end,
	} )
end

---- specific LSPs ----

local lsplang = require('lspconfig.configs')

lsplang.rhombus = {
	default_config = {
		cmd = {"racket",  "-l", "racket-langserver"},
		filetypes = { "rhombus" },
		root_dir = vim.fs.dirname,
		settings = {},
	},
}

lsplang.flix = {
	default_config = {
		cmd = {"flix", "lsp"},
		filetypes = { "flix" },
		root_dir = function(fname)
			-- Search for flix.toml/flix.jar upwards recursively, with a fallback to the current directory
			local root_dir = vim.fs.dirname(vim.fs.find({"flix.toml", "flix.jar"}, { path = fname, upward = true })[1])
				or vim.fs.dirname(fname)
			return root_dir
		end,
		settings = {},
	},
	on_attach = function(client, _)
		client.commands["flix.runMain"] = function(_, _)
			vim.cmd("terminal flix run")
		end
	end
}
-- not through vim.lsp because i don't know yet how to configure the default config
if first_run then
	lsplang.rhombus.setup {}
	lsplang.flix.setup {}
end

vim.lsp.config.powershell_es = {
	bundle_path = '~/.local/lib/PowerShellEditorServices',
}
vim.lsp.config.perlnavigator = {
	settings = {
		perlnavigator = {
			perlcriticEnabled = false,
		}
	}
}

vim.lsp.config('oxc', {
	cmd = {"oxc_language_server"},
	root_dir = function(buf, on_dir)
		local dir = vim.fs.root(0, { 'package.json', 'tsconfig.json' })  -- order matters
		if dir then on_dir(dir) end
	end,
})

for _, lsp in ipairs({'clangd', 'rust-analyzer', 'lua_ls', 'bashls', 'pylsp', 'ts_ls', 'gopls', 'clojure_lsp', 'oxc', 'cssls', 'markdown_oxide'}) do
	vim.lsp.enable(lsp)
end

---- Filetypes ----

vim.filetype.add { extension = {
	m     = 'mumps',
	ua    = 'uiua',
	rhm   = 'rhombus',
	flix  = 'flix',
} }

vim.api.nvim_create_autocmd("FileType", { callback = function()
	local ft = vim.bo.filetype
	if ft == "uiua" then
		vim.bo.commentstring = '#%s'
	elseif ft == "rhombus" then
		vim.bo.commentstring = '//%s'
	elseif ft == "mumps" then
		vim.bo.commentstring = ';%s'
		vim.cmd('highlight! link Keyword Special')
	end
end })

vim.api.nvim_create_autocmd("ColorScheme", { callback = function()
	local ft = vim.bo.filetype
	if ft == 'mumps' then
		vim.cmd('highlight! link Keyword Special')
	end
end })

vim.api.nvim_create_autocmd("FileType", {
	pattern = "markdown",
	callback = function()
		vim.wo.colorcolumn = ""
		vim.fn.mkdir('assets', 'p') -- for image pasting

		bind_ts(ts {
			h = 'class', -- no clue why TS calls headers "classes" but sure whatever
			-- why is this inconsistent with locals :((
			v = { capture = 'variable', group = 'textobjects', no_suffix = true, },
		})
		-- match obsidian bindings
		vim.keymap.set({'n', 'v'}, '<C-b>', ":Mdn formatting strong_toggle<CR>", {desc = 'Toggle bold', buffer = true })
		vim.keymap.set({'n', 'v'}, '<C-i>', ":Mdn formatting emphasis_toggle<CR>", {desc = 'Toggle italics', buffer = true })
		vim.keymap.set({'n', 'v'}, '<C-l>', ":Mdn formatting task_list_toggle<CR>", {desc = 'Toggle checkbox', buffer = true })
		vim.keymap.set({'n', 'v'}, '<C-`>', ":Mdn formatting inline_code_toggle<CR>", {desc = 'Toggle inline code', buffer = true })
		vim.keymap.set({'n', 'v'}, '<C-S-K>', ":Mdn inline_link toggle<CR>", {desc = 'Toggle link', buffer = true })
		vim.keymap.set({'n', 'v'}, '<leader>t', ":Mdn toc generate<CR>", {desc = 'Generate table of contents', buffer = true })
		vim.keymap.set({'n', 'v', 'i'}, '<C-S-V>', "<cmd>Mdn assets insert_image<CR>", {desc = 'Paste image', buffer = true})
		vim.keymap.set({'n', 'v', 'i'}, '<Tab>', "<cmd>norm! >><CR>", {desc = 'Indent', buffer = true, noremap = true})
		vim.keymap.set({'n', 'v', 'i'}, '<S-Tab>', "<cmd>norm! <<<CR>", {desc = 'Indent', buffer = true, noremap = true})

		-- <C-f> to create a footnote

		local snippet = '```${1:}\n${2:body}${0}\n```'
		vim.keymap.set({'n', 'v', 'i'}, '<C-\'>', function()
			vim.snippet.expand(snippet)
		end, {desc = 'Create code block', buffer = true})
	end
})

---- Rust-specific config ----

-- https://stackoverflow.com/a/326715
function os.capture(cmd)
	local f = assert(io.popen(cmd, 'r'))
	local s = assert(f:read('*a'))
	f:close()
	return s
end
-- https://stackoverflow.com/a/72921992
function string:endswith(suffix)
	return self:sub(-#suffix) == suffix
end
function rustfmt_is_nightly()
	-- rustfmt --version is inexplicably slow if it's not installed for the current toolchain
	if os.execute("rustup which rustfmt >/dev/null 2>&1") then return false end
	-- split string on whitespace: https://stackoverflow.com/a/7615129
	local version = string.gmatch(os.capture("rustfmt --version"), "([^%s]+)")
	local second = version()
	return second ~= nil and second:endswith '-nightly'
end

local function expand_config_variables(option)
	local var_placeholders = {
		['${workspaceFolder}'] = function(_)
			return vim.lsp.buf.list_workspace_folders()[1]
		end,
	}

	if type(option) == "table" then
		local mt = getmetatable(option)
		local result = {}
		for k, v in pairs(option) do
			result[expand_config_variables(k)] = expand_config_variables(v)
		end
		return setmetatable(result, mt)
	end
	if type(option) ~= "string" then
		return option
	end
	local ret = option
	for key, fn in pairs(var_placeholders) do
		ret = ret:gsub(key, fn)
	end
	return ret
end

local fs_exists = vim.uv.fs_stat

function setup_ra()
	if not vim.bo.filetype == "rust" then
		return
	end
	local settings = { ['rust-analyzer'] = { rustfmt = { rangeFormatting = { enable = rustfmt_is_nightly() } } } }
	vim.lsp.config('rust-analyzer', {
		cmd = { "rust-analyzer" },
		filetypes = { "rust" },
		settings = settings,
		root_dir = function(buf, on_dir)
			local dir = vim.fs.root(0, { 'x.py', 'Cargo.toml' })  -- order matters
			if not dir then return end
			if vim.fs.basename(dir) == "library" and fs_exists(vim.fs.joinpath(dir, "../src/bootstrap/defaults/config.compiler.toml")) then
				dir = vim.fs.dirname(dir)
			end
			on_dir(dir)
		end,
		-- not sure why this needs to be set here, but https://www.reddit.com/r/neovim/comments/1cyfgqt/getting_range_formatting_to_work_with_mason_or/ claims it does
		-- init_options = settings,
		on_init = function(client)
			local path = vim.lsp.buf.list_workspace_folders()[1]
			-- rust-lang/rust
			config = vim.fs.joinpath(path, "src/etc/rust_analyzer_zed.json")
			if fs_exists(config) then
				modified_config = vim.fs.joinpath(path, ".zed/settings.json")
				if fs_exists(modified_config) then
					config = modified_config
				end
				file = io.open(config)
				json = vim.json.decode(file:read("*a"))
				client.config.settings["rust-analyzer"] = expand_config_variables(json.lsp["rust-analyzer"].initialization_options)
				client.notify("workspace/didChangeConfiguration", { settings = client.config.settings })
			end
		end
	})
end

vim.api.nvim_create_autocmd('BufReadPre', {
	desc = 'Setup rust-analyzer',
	callback = setup_ra
})

---- Session and meta config ----

-- begin saving session immediately on startup
if vim.fn.ObsessionStatus('a') ~= 'a' and not fs_exists('.session.vim') then
	vim.cmd.Obsess(".session.vim")
end

if not first_run then
	-- vim.cmd.bufdo('silent! edit')
	-- vim.cmd.bufdo('LspRestart')
end
