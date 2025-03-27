---@diagnostic disable: lowercase-global
---
-- skeleton comes from https://github.com/nvim-lua/kickstart.nvim/blob/5bdde24dfb353d365d908c5dd700f412ed2ffb17/init.lua
-- use `:verbose set foo` to see where option `foo` is set

---- Options ----

vim.g.mapleader = ' '
vim.g.maplocalleader = 'f'
vim.opt.number = true
vim.opt.breakindent = true
vim.opt.undofile = true
vim.opt.ignorecase = true
vim.opt.wildignorecase = true
vim.opt.smartcase = true
vim.opt.scrolloff = 3
vim.opt.sidescrolloff = 10
vim.opt.visualbell = true
vim.opt.title = true  -- allows S-d to search for a file
-- see `:help zo` for keybinds
vim.opt.shiftround = true      -- TODO: disable this for markdown and mumps files

vim.opt.list = true
vim.opt.listchars = { tab = '│ ', trail = '·', nbsp = '␣' }
-- shows :s/foo/bar preview live
vim.opt.inccommand = 'split'

vim.cmd.set('clipboard=unnamed')

vim.api.nvim_create_autocmd('TextYankPost', {
	desc = 'Highlight when copying text',
	callback = function() vim.highlight.on_yank() end,
})

vim.api.nvim_create_autocmd('VimResized', {
	desc = 'Automatically equalize windows on terminal size change',
	command = 'wincmd ='
})

---- Filetype options
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
function hard_tabs(count)
	vim.bo.expandtab = false
	vim.bo.tabstop = count
	vim.bo.softtabstop = count
	vim.bo.shiftwidth = count
end
function spaces(count)
	vim.bo.expandtab = true
	vim.bo.tabstop = 8
	vim.bo.softtabstop = count
	vim.bo.shiftwidth = count
end
indentgroup('lua', function() hard_tabs(2) end)
indentgroup('sh', function() hard_tabs(2) end)
indentgroup('rust', function() spaces(4) end)
indentgroup('toml', function() spaces(4) end)
indentgroup('c', function() hard_tabs(8) end)
-- llvm uses 2 spaces and llvm is the only c++ codebase i care about
indentgroup('cpp', function() spaces(2) end)

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

vim.keymap.set('n', '<A-Left>', '<C-o>', { desc = 'Go back in history' })
vim.keymap.set('n', '<A-Right>', '<C-i>', { desc = 'Go forward in history' })

vim.keymap.set('n', '<A-i>', 'i_<Esc>r', { desc = 'Insert a single character' })

vim.keymap.set('', '<S-ScrollWheelDown>', '5zl', { desc = 'Scroll right' })
vim.keymap.set('', '<S-ScrollWheelUp>', '5zh', { desc = 'Scroll left' })
vim.keymap.set('', '<A-ScrollWheelDown>', '<C-d>', { desc = 'Scroll page up' })
vim.keymap.set('', '<A-ScrollWheelUp>', '<C-u>', { desc = 'Scroll page down' })

vim.keymap.set('n', '<leader>t', function()
	vim.cmd.wall()
	vim.cmd.make('test')
end, { desc = "Run `make test`" })
-- TODO: add ninja output to `errorformat` (see `:h efm-ignore`)

-- add some helix keybinds
vim.keymap.set('n', 'U', '<C-r>', { desc = "Redo" }) -- overwrites "undo line" with no replacement
-- TODO: this reopens closed buffers lol
vim.keymap.set('n', 'ga', ':b#<cr>', { desc = "Go to most recently used buffer" }) -- overwrites `:as[cii]` keybind
vim.keymap.set('n', 'gn', ':bnext<cr>', { desc = "Go to next buffer" }) -- overwrites `nv` keybind
vim.keymap.set('n', 'gp', ':bprevious<cr>', { desc = "Go to previous buffer" }) -- overwrites "paste before cursor"

-- vim.keymap.set('n', 'n', 'gn', { desc = "Select next search result", noremap })
-- vim.keymap.set('v', 'n', function()
-- 	vim.cmd.startinsert()
-- 	vim.cmd.normal('gn')
-- end, { desc = "Go to next buffer", noremap })

-- note: overwrites select mode
vim.keymap.set({'n', 'v'}, 'gh', '^', { desc = "Go to line start" })
vim.keymap.set({'n', 'v'}, 'gl', '$', { desc = "Go to line end" })

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

vim.api.nvim_create_user_command('EditConfig', 'edit ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
vim.api.nvim_create_user_command('ReloadConfig', 'source ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
vim.api.nvim_create_user_command('Rename', function(info)
	-- NOTE: :sav doesn't preserve permissions
	vim.cmd('silent !mv ' .. vim.fn.expand('%') .. ' ' .. info.args)
	vim.cmd.edit(info.args)
	vim.cmd.bdelete('#')
end, { nargs=1, desc = "Rename current file" })

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
vim.api.nvim_create_user_command('OpenRemoteUrl', function(info)
	local file = vim.api.nvim_buf_get_name(0)
	local out = vim.system({'remote-git-url', file, tostring(info.line1), tostring(info.line2)}, {text=true}):wait()
	if out.stderr ~= '' then
		error(out.stderr)
	end
	if out.stdout ~= '' then
		vim.notify(out.stdout)
	end
end, {
	range = true,
	desc = "Open the current line on a git host at the last commit at which it was modified"
})

-- autosave on cursor hold
local timers = {}
function autosave_enable()
	local buf = vim.api.nvim_get_current_buf()
	if timers[buf] then
		return
	end

	local buf_name = vim.fn.expand '%'
	print("autosaving "..buf_name)
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
		table.remove(timers, buf)
	end
end
vim.api.nvim_create_user_command('AutoSaveDisable', autosave_disable, {desc = "Stop autosaving"})

-- https://vi.stackexchange.com/a/33221
function abbrev(lhs, rhs)
	vim.cmd.cabbrev('<expr>', lhs..' (getcmdtype() == ":") ? "'..rhs..'" : "'..lhs..'"')
end
abbrev('Q', 'quit')
abbrev('open', 'edit')
abbrev('o', 'edit')
abbrev('W', 'w')
abbrev('bc', 'BufferDelete')
abbrev('mv', 'Rename')
abbrev('ec', 'EditConfig')
abbrev('url', 'OpenRemoteUrl')
abbrev('as', 'AutoSave')

-- disable some warnings
vim.g.loaded_node_provider = 0
vim.g.loaded_perl_provider = 0
vim.g.loaded_ruby_provider = 0

local fs_exists = vim.uv.fs_stat

---- Plugins ----

-- Bootstrap lazy.nvim
local first_run = not vim.g.lazy_did_setup
if first_run then
	local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
	vim.opt.rtp:prepend(lazypath)

	require("lazy").setup({
		{ "folke/lazydev.nvim", ft = "lua", opts = {
				-- See the configuration section for more details
				-- Load luvit types when the `vim.uv` word is found
				library = { { path = "${3rd}/luv/library", words = { "vim%.uv" } } },
		} },
		'tpope/vim-obsession',  -- session save/resume
		'numToStr/Comment.nvim',
		{ 'nvim-telescope/telescope.nvim', dependencies = {'nvim-lua/plenary.nvim'} },  -- general picker
		'kosayoda/nvim-lightbulb',
		'echasnovski/mini.nvim',    -- toolbar, also icons
		"folke/which-key.nvim",     -- spawns kak/hx-like popup
		'lewis6991/gitsigns.nvim',  -- also does inline blame
		{ "chrisgrieser/nvim-spider", lazy = true },  -- partial word movement
		{ 'vxpm/rust-expand-macro.nvim', lazy = true },
		'neovim/nvim-lspconfig',
		{ 'jyn514/alabaster.nvim', branch = 'dark' },
		'mfussenegger/nvim-dap',    -- debugging
		{ "rcarriga/nvim-dap-ui", dependencies = {"mfussenegger/nvim-dap", "nvim-neotest/nvim-nio"} },
		'nvim-telescope/telescope-ui-select.nvim',
		{'hrsh7th/cmp-cmdline', dependencies = 'hrsh7th/nvim-cmp' },

		-- https://github.com/smoka7/hop.nvim  -- random access within file

		-- not going to bother setting this up until https://github.com/neovim/neovim/issues/24690 is fixed
		-- https://github.com/amitds1997/remote-nvim.nvim
	}, { install = { missing = true }, rocks = { enabled = false } })
end

vim.g.alabaster_dim_comments = true

cmp = require 'cmp'
cmp.setup {
	snippet = { expand = function(args) vim.snippet.expand(args.body) end },
}
cmp.setup.cmdline(':', {
	mapping = cmp.mapping.preset.cmdline(),
	sources = cmp.config.sources(
		{{ name = 'path' }},
		{{ name = 'cmdline' }}
	),
	matching = { disallow_symbol_nonprefix_matching = false }
})

require('Comment').setup()
local ft_comment = require('Comment.ft')
-- require('Comment.ft').set('dl', {'//%s', '/*%s*/'})
ft_comment.set('flix', ft_comment.get('c'))
ft_comment.set('rhombus', ft_comment.get('c'))
vim.keymap.set('n', '<C-_>', 'gcc', {remap = true})
vim.keymap.set('n', '<C-c>', 'gcc', {remap = true})
-- TODO: find a way to only comment out the selected region
-- using blockwise comments doesn't work in all filetypes
vim.keymap.set('v', '<C-_>', 'gc', {remap = true})
vim.keymap.set('v', '<C-c>', 'gc', {remap = true})

-- If this doesn't look right, try `:set termguicolors`.
-- SSH should be forwarding $COLORTERM, which sets it automatically, but some ssh servers block it unless you add `AcceptEnv COLORTERM`.
vim.cmd.colorscheme 'alabaster-black'

local telescope = require('telescope')
telescope.setup {
	defaults = { mappings = {
		n = {
			["<C-c>"] = require('telescope.actions').close
		}
	} },
	extensions = {
		["ui-select"] = {
			vim.tbl_deep_extend("force", require'telescope.themes'.get_ivy(), {
				layout_config = {
					height = { .1, min = 5 },
				}
			})
		}
	}
}
telescope.load_extension 'ui-select'

local pickers = require('telescope.builtin')
vim.keymap.set('n', '<leader>b', function() pickers.buffers({ sort_mru = true, ignore_current_buffer = true }) end, { desc = "Open buffer picker" })
vim.keymap.set('n', '<leader>f', pickers.find_files, { desc = "Open file picker" })
vim.keymap.set('n', '<leader><A-f>', function()
	pickers.find_files({ no_ignore = true, no_ignore_parent = true, hidden = true })
end, { desc = "Open file picker (include ignored)" })
vim.keymap.set('n', '<leader>F', pickers.oldfiles, { desc = "Open file picker (all files ever opened)" })
vim.keymap.set('n', '<leader>/', function()
	pickers.live_grep({prompt_title = "Live Search"})
end, { desc = "Search in workspace" })
vim.keymap.set('n', '<leader>g', function()
	pickers.git_files({ git_command = {"git", "ls-files", "--modified"}, prompt_title = "Modified Files" })
end, { desc = "Modified files" })

require("nvim-lightbulb").setup({
	autocmd = { enabled = true }
})

require('mini.icons').setup {}
MiniStatusline = require'mini.statusline'
MiniStatusline.setup {
	content = {
		active = function()
			local git           = MiniStatusline.section_git({ trunc_width = 40 })
			local diff          = MiniStatusline.section_diff({ trunc_width = 75 })
			local diagnostics   = MiniStatusline.section_diagnostics({ trunc_width = 75 })
			local lsp           = MiniStatusline.section_lsp({ trunc_width = 75 })
			local filename      = MiniStatusline.section_filename({ trunc_width = 140 })
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
			{ "<auto>", mode = "nxso" },
			{ "<localleader>", mode = {'n', 'v'} }
		}
	})
	wk.add({
		{ '<LocalLeader>', group = "Debugging" },
	})
end

require('gitsigns').setup({
	current_line_blame = true,
	signs = {
		add = { text = '+' },
		change = { text = '~' },
		--[[ delete = { text = '_' },
		topdelete = { text = '‾' }, ]]
		changedelete = { text = '~' },
	}
})

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

---- Debugging ----
local dap = require('dap')
dap.adapters.cppdbg = {
  id = 'cppdbg',
  type = 'executable',
  command = '/home/jyn/.local/share/nvim/lazy/vimspector/gadgets/linux/vscode-cpptools/debugAdapters/bin/OpenDebugAD7',
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
vim.keymap.set('n', 'gd', '<C-]>', { desc = "Goto definition" })
vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, { desc = "Goto declaration" })
vim.keymap.set('n', 'gr', pickers.lsp_references, { desc = "Find references" })
vim.keymap.set('n', 'gy', pickers.lsp_type_definitions, { desc = "Goto type definition" })
vim.keymap.set('n', 'gi', pickers.lsp_implementations, { desc = "Goto type implementation" })
vim.keymap.set('n', '<leader>.', vim.lsp.buf.code_action, { desc = "LSP code action" })
vim.keymap.set('n', '<leader>r', vim.lsp.buf.rename, { desc = "Rename symbol" })
vim.keymap.set('n', '<leader>s', pickers.lsp_document_symbols, { desc = "Show symbols in the current buffer" })
vim.keymap.set('n', '<leader>S', pickers.lsp_workspace_symbols, { desc = "Show all symbols in the workspace" })
vim.keymap.set('n', '<leader>d', ':Telescope diagnostics<cr>:error: ', { desc = "Show workspace diagnostics (errors)" })
vim.keymap.set('n', '<leader>D', pickers.diagnostics, { desc = "Show workspace diagnostics (all)" })
vim.keymap.set('n', '<leader>e', vim.diagnostic.open_float, { desc = "Show details for errors on the current line" })
vim.keymap.set({'n','v'}, 'g=', vim.lsp.buf.format, { desc = "Format whole file" })

vim.api.nvim_create_autocmd("User", {
	pattern = "TelescopePreviewerLoaded",
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
		vim.keymap.set('n', '<leader>l', vim.lsp.codelens.run, { desc = "Run codelens" })
		vim.api.nvim_create_autocmd({ "CursorMoved" }, {
			callback = vim.lsp.codelens.refresh,
			buffer = bufnr,
			desc = "Refresh codelens actions",
		})
	end
end })

-- needs nvim 11
--[[
vim.api.nvim_create_autocmd('LspNotify', {
	callback = function(args)
		if args.data.method == 'textDocument/didOpen' then
			vim.lsp.foldclose('imports', vim.fn.bufwinid(args.buf))
		end
	end,
} )
]]

---- specific LSPs ----
require('vim.lsp.log').set_format_func(vim.inspect)

local lspconfig = require('lspconfig')
local lsplang = require('lspconfig.configs')

if not lsplang.rhombus then
	lsplang.rhombus = {
		default_config = {
			cmd = {"racket",  "-l", "racket-langserver"},
			filetypes = { "rhombus" },
			root_dir = vim.fs.dirname,
			settings = {},
		},
	}
end

lspconfig.clangd.setup {}
lspconfig.bashls.setup {}
lspconfig.pylsp.setup {}
lspconfig.uiua.setup {}
lspconfig.rhombus.setup {}
lspconfig.flix.setup {
	on_attach = function(client , bufnr)
		client.commands["flix.runMain"] = function(command, context)
			vim.cmd("terminal flix run")
		end
	end
}

vim.filetype.add { extension = {
	m     = 'mumps',
	-- dl = 'dl', //%s
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
	if vim.bo.syntax == 'mumps' then
		vim.cmd('highlight! link Keyword Special')
	end
end })

if first_run then
	lspconfig.powershell_es.setup {
		bundle_path = '~/.local/lib/PowerShellEditorServices',
	}
end
-- this doesn't seem to work?
-- lspconfig.esbonio.setup {}
lspconfig.perlnavigator.setup {
	settings = {
		perlnavigator = {
			perlcriticEnabled = false,
		}
	}
}

lspconfig.lua_ls.setup {}

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
	-- https://stackoverflow.com/a/7615129
	local version = string.gmatch(os.capture("rustfmt --version"), "([^%s]+)")
	version()
	return version():endswith '-nightly'
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

local settings = { ['rust-analyzer'] = { rustfmt = { rangeFormatting = { enable = rustfmt_is_nightly() } } } }
lspconfig.rust_analyzer.setup {
	cmd = { "rust-analyzer", "+nightly" },
	settings = settings,
	root_dir = function()
		default = lspconfig.rust_analyzer.config_def.default_config.root_dir()
		if vim.fs.basename(default) == "library" and fs_exists(vim.fs.joinpath(default, "../src/bootstrap/defaults/config.compiler.toml")) then
			return vim.fs.dirname(default)
		end
		return default
	end,
	-- not sure why this needs to be set here, but https://www.reddit.com/r/neovim/comments/1cyfgqt/getting_range_formatting_to_work_with_mason_or/ claims it does
	-- init_options = settings,
	on_init = function(client)
		local path = client.workspace_folders[1].name
		-- rust-lang/rust
		config = vim.fs.joinpath(path, "src/etc/rust_analyzer_zed.json")
		if fs_exists(config) then
			file = io.open(config)
			json = vim.json.decode(file:read("*a"))
			client.config.settings["rust-analyzer"] = expand_config_variables(json.lsp["rust-analyzer"].initialization_options)
			client.notify("workspace/didChangeConfiguration", { settings = client.config.settings })
		end

		return true
	end
}

local expand_macro = require('rust-expand-macro').expand_macro
vim.api.nvim_create_user_command('ExpandMacro', expand_macro, {desc = "Expand macro recursively"})

-- begin saving session immediately on startup
if vim.fn.ObsessionStatus('a') ~= 'a' and not fs_exists('Session.vim') then
	vim.cmd.Obsess()
end
