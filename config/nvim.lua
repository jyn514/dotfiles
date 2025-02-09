---@diagnostic disable: lowercase-global
-- skeleton comes from https://github.com/nvim-lua/kickstart.nvim/blob/5bdde24dfb353d365d908c5dd700f412ed2ffb17/init.lua

---- Options ----

vim.g.mapleader = ' '
vim.g.maplocalleader = ' '
vim.opt.number = true
vim.opt.breakindent = true
vim.opt.undofile = true
vim.opt.ignorecase = true
vim.opt.smartcase = true

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
			if event.file == lang then
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

-- add some helix keybinds
vim.keymap.set('n', 'U', '<C-r>', { desc = "Redo" }) -- overwrites "undo line" with no replacement
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

	-- completion
	vim.keymap.set('i', '<C-n>', '<C-x><C-o>', { desc = "Trigger omnicompletion" }) -- overwrites "complete keyword"
	vim.keymap.set('i', '<C-c>', function()
		return vim.fn.pumvisible() and '<C-e>' or '<C-c>'
	end, { expr = true, desc = "Cancel completion" }) -- overwrites "return to normal mode immediately"

	vim.api.nvim_create_user_command('EditConfig', 'edit ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
	vim.api.nvim_create_user_command('ReloadConfig', 'source ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
	vim.api.nvim_create_user_command('Rename', function(info)
		vim.cmd.sav(info.args)
		vim.fn.delete(vim.fn.expand('#'))
		vim.cmd.bdelete('#')
	end, { nargs=1, desc = "Rename current file" })
	vim.api.nvim_create_user_command('OpenRemoteUrl', function(info)
		local line = vim.api.nvim_win_get_cursor(0)[1]
		local file = vim.api.nvim_buf_get_name(0)
		local out = vim.system({'remote-git-url', file, tostring(line)}, {text=true}):wait()
		if out.stderr ~= '' then
			error(out.stderr)
		end
	end, { desc = "Open the current line on a git host at the last commit at which it was modified" })

	-- https://vi.stackexchange.com/a/33221
	function abbrev(lhs, rhs)
		vim.cmd.cabbrev('<expr>', lhs..' (getcmdtype() == ":") ? "'..rhs..'" : "'..lhs..'"')
	end
	abbrev('Q', 'quit')
	abbrev('open', 'edit')
	abbrev('o', 'edit')
	abbrev('W', 'w')
	abbrev('bc', 'bdelete')
	abbrev('mv', 'Rename')
	abbrev('ec', 'EditConfig')
	abbrev('url', 'OpenRemoteUrl')

	-- disable some warnings
	vim.g.loaded_node_provider = 0
	vim.g.loaded_perl_provider = 0
	vim.g.loaded_ruby_provider = 0

	---- Plugins ----

	-- Bootstrap lazy.nvim
	local first_run = not vim.g.lazy_did_setup
	if first_run then
		local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
		vim.opt.rtp:prepend(lazypath)

		require("lazy").setup({
			'tpope/vim-obsession',
			'numToStr/Comment.nvim',
			{ 'nvim-telescope/telescope.nvim', dependencies = {'nvim-lua/plenary.nvim'} },
			'kosayoda/nvim-lightbulb',
			'echasnovski/mini.nvim',
			"folke/which-key.nvim",
			'lewis6991/gitsigns.nvim',
			{ "chrisgrieser/nvim-spider", lazy = true },
			{ 'vxpm/rust-expand-macro.nvim', lazy = true },
			'neovim/nvim-lspconfig',
			{ 'jyn514/alabaster.nvim', branch = 'dark' },
			-- https://github.com/amitds1997/remote-nvim.nvim looks promising
		}, { install = { missing = true }, rocks = { enabled = false } })
	end

	vim.g.alabaster_dim_comments = true

	require('Comment').setup()
	vim.keymap.set('n', '<C-_>', 'gcc', {remap = true})
	vim.keymap.set('n', '<C-c>', 'gcc', {remap = true})
	-- TODO: find a way to only comment out the selected region
	-- using blockwise comments doesn't work in all filetypes
	vim.keymap.set('v', '<C-_>', 'gc', {remap = true})
	vim.keymap.set('v', '<C-c>', 'gc', {remap = true})

	vim.cmd.colorscheme 'alabaster-black'

	require('telescope').setup {
		defaults = { mappings = {
			n = {
				["<C-c>"] = require('telescope.actions').close
			}
		} }
	}

	local pickers = require('telescope.builtin')
	vim.keymap.set('n', '<leader>b', pickers.buffers, { desc = "Open buffer picker" })
	vim.keymap.set('n', '<leader>f', pickers.find_files, { desc = "Open file picker" })
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

				return MiniStatusline.combine_groups({
					{ hl = 'Normal', strings = { filename } },
					{ hl = 'Conceal',  strings = { git, diff, diagnostics, lsp } },
					'%<', -- Mark general truncate point
					'%=', -- End left alignment
					{ hl = 'Conceal', strings = { fileinfo, location } },
				})
			end
		}
	}
	if first_run then
		require('which-key').setup({preset = 'helix', delay = 150, icons = {mappings = false}})
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

	---- LSP ----
	vim.keymap.set('n', 'gd', '<C-]>', { desc = "Goto definition" })
	vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, { desc = "Goto declaration" })
	vim.keymap.set('n', 'gr', pickers.lsp_references, { desc = "Find references" })
	vim.keymap.set('n', 'gy', pickers.lsp_type_definitions, { desc = "Goto type definition" })
	vim.keymap.set('n', '<leader>.', vim.lsp.buf.code_action, { desc = "LSP code action" })
	vim.keymap.set('n', '<leader>r', vim.lsp.buf.rename, { desc = "Rename symbol" })
	vim.keymap.set('n', '<leader>s', pickers.lsp_document_symbols, { desc = "Show symbols in the current buffer" })
	vim.keymap.set('n', '<leader>S', pickers.lsp_workspace_symbols, { desc = "Show all symbols in the workspace" })
	vim.keymap.set('n', '<leader>d', ':Telescope diagnostics<cr>:error: ', { desc = "Show workspace diagnostics (errors)" })
	vim.keymap.set('n', '<leader>D', pickers.diagnostics, { desc = "Show workspace diagnostics (all)" })
	vim.keymap.set('n', '<leader>e', vim.diagnostic.open_float, { desc = "Show details for errors on the current line" })
	vim.keymap.set({'n','v'}, 'g=', vim.lsp.buf.format, { desc = "Format whole file" })

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
	end
})

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

lspconfig.clangd.setup {}
lspconfig.bashls.setup {}
lspconfig.pylsp.setup {}

lspconfig.uiua.setup {}
vim.filetype.add { extension = { ua = 'uiua' } }
vim.filetype.add { extension = { m = 'mumps' } }
vim.api.nvim_create_autocmd("FileType", { callback = function()
	local ft = vim.fn.expand("<amatch>")
	if ft == "uiua" then
		vim.bo.commentstring = '#%s'
	elseif ft == "mumps" then
		vim.bo.commentstring = ';%s'
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

-- https://github.com/neovim/nvim-lspconfig/blob/master/doc/configs.md#lua_ls
lspconfig.lua_ls.setup {
	on_init = function(client)
		if client.workspace_folders then
			local path = client.workspace_folders[1].name
			if path ~= vim.fn.stdpath('config') and vim.loop.fs_stat(path..'/.luarc.json') or vim.loop.fs_stat(path..'/.luarc.jsonc') then
				print("not the right config file: "..path)
				return
			end
		end

		client.config.settings.Lua = vim.tbl_deep_extend('force', client.config.settings.Lua, {
			runtime = {
				-- Tell the language server which version of Lua you're using
				-- (most likely LuaJIT in the case of Neovim)
				version = 'LuaJIT'
			},
			-- Make the server aware of Neovim runtime files
			workspace = {
				checkThirdParty = false,
				library = {
					vim.env.VIMRUNTIME,
					-- Depending on the usage, you might want to add additional paths here.
					"${3rd}/luv/library",
					-- "${3rd}/busted/library",
				}
				-- or pull in all of 'runtimepath'. NOTE: this is a lot slower and will cause issues when working on your own configuration (see https://github.com/neovim/nvim-lspconfig/issues/3189)
				-- library = vim.api.nvim_get_runtime_file("", true)
			}
		})
	end,
	settings = {
		Lua = {}
	}
}

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

local settings = { ['rust-analyzer'] = { rustfmt = { rangeFormatting = { enable = true } } } }
lspconfig.rust_analyzer.setup {
	cmd = { '/home/jyn/.local/lib/cargo/target/release/rust-analyzer' },
	settings = settings,
	-- not sure why this needs to be set here, but https://www.reddit.com/r/neovim/comments/1cyfgqt/getting_range_formatting_to_work_with_mason_or/ claims it does
	-- init_options = settings,
	on_init = function(client)
		if rustfmt_is_nightly() then
			if vim.bo.filetype == 'rust' then vim.opt_local.formatexpr = 'v:lua.formatexpr()' end
			client.on_attach = function()
				if vim.bo.filetype == 'rust' then vim.opt_local.formatexpr = 'v:lua.formatexpr()' end
			end
		end
	end
}

local expand_macro = require('rust-expand-macro').expand_macro
vim.api.nvim_create_user_command('ExpandMacro', expand_macro, {desc = "Expand macro recursively"})

-- vim.g.VM_leader = ','

--[[ ---- Multicursor ----

local mc = require('multicursor-nvim')
mc.setup()
function mc_set(keybind, action, desc) vim.keymap.set({"n", "v"}, keybind, action, {desc = desc}) end

mc_set("<esc>", function()
	-- print('sid: '.. vim.fn.expand('<SID>'))
	if not mc.cursorsEnabled() then
		mc.enableCursors()
	elseif mc.hasCursors() then
		mc.clearCursors()
	else
		-- Default <esc> handler.
		local mode = vim.api.nvim_get_mode().mode
		if mode == 'n' then
			vim.cmd.nohlsearch()
		elseif mode == 'v' then
			vim.cmd.normal('v')
		end
		-- local map = vim.api.nvim_get_keymap(vim.api.nvim_get_mode().mode)
		-- -- local binding = vim.fn.maparg('<Esc>', vim.api.nvim_get_mode().mode)
		-- print('sid: '.. vim.fn.expand('<SID>'))
		-- for _,val in pairs(map) do
		-- 	print(val.sid)
		-- 	if val.lhs == '<Esc>' and vim.fn.expand('<SID>') ~= val.sid then
		-- 		if val.callback ~= nil then
		-- 			val.callback()
		-- 		elseif val.rhs then
		-- 			vim.cmd(val.rhs)
		-- 		end
		-- 	end
		-- end
		-- print(binding)
		-- binding()
	end
end)

mc_set('<up>', function() mc.lineAddCursor(-1) end, "Add cursor on line above")
mc_set('<down>', function() mc.lineAddCursor(1) end, "Add cursor on line below")
mc_set('<leader><up>', function() mc.lineSkipCursor(-1) end, "Move main cursor line up")
mc_set('<leader><down>', function() mc.lineSkipCursor(1) end, "Move main cursor line down")
mc_set('<leader><n>', function() mc.matchAddCursor(1) end, "Add cursor on next matching word")

-- Add or skip adding a new cursor by matching word/selection
mc_set("<leader>n", function() mc.matchAddCursor(1) end)
mc_set("<leader>N",
function() mc.matchAddCursor(-1) end)
-- set({"n", "v"}, "<leader>s",
--     function() mc.matchSkipCursor(1) end)
-- set({"n", "v"}, "<leader>S",
--     function() mc.matchSkipCursor(-1) end)

-- Add all matches in the document
mc_set("<leader>A", mc.matchAllAddCursors)

-- You can also add cursors with any motion you prefer:
-- set("n", "<right>", function()
	--     mc.addCursor("w")
	-- end)
	-- set("n", "<leader><right>", function()
		--     mc.skipCursor("w")
		-- end)

		-- Rotate the main cursor.
		mc_set("<left>", mc.nextCursor)
		mc_set("<right>", mc.prevCursor)

		-- Delete the main cursor.
		mc_set("<leader>x", mc.deleteCursor)

		-- Add and remove cursors with control + left click.
		-- set("n", "<c-leftmouse>", mc.handleMouse)

		-- Easy way to add and remove cursors using the main cursor.
		mc_set("<c-q>", mc.toggleCursor)

		-- Clone every cursor and disable the originals.
		-- set({"n", "v"}, "<leader><c-q>", mc.duplicateCursors)

		-- bring back cursors if you accidentally clear them
		vim.keymap.set("n", "<leader>gv", mc.restoreCursors)

		-- Align cursor columns.
		-- set("n", "<leader>a", mc.alignCursors)

		-- Split visual selections by regex.
		-- set("v", "S", mc.splitCursors)

		-- Append/insert for each line of visual selections.
		vim.keymap.set("v", "I", mc.insertVisual)
		vim.keymap.set("v", "A", mc.appendVisual)

		-- match new cursors within visual selections by regex.
		vim.keymap.set("v", "M", mc.matchCursors)

		-- Rotate visual selection contents.
		vim.keymap.set("v", "<leader>t", function() mc.transposeCursors(1) end)
		vim.keymap.set("v", "<leader>T", function() mc.transposeCursors(-1) end)

		-- Jumplist support
		mc_set("<c-i>", mc.jumpForward)
		mc_set("<c-o>", mc.jumpBackward)

		-- Customize how cursors look.
		local hl = vim.api.nvim_set_hl
		hl(0, "MultiCursorCursor", { link = "Cursor" })
		hl(0, "MultiCursorVisual", { link = "Visual" })
		hl(0, "MultiCursorSign", { link = "SignColumn"})
		hl(0, "MultiCursorDisabledCursor", { link = "Visual" })
		hl(0, "MultiCursorDisabledVisual", { link = "Visual" })
		hl(0, "MultiCursorDisabledSign", { link = "SignColumn"})
		]]
