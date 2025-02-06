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

---- Keybinds ----

-- Clear highlights on search when pressing <Esc> in normal mode
vim.keymap.set('n', '<Esc>', '<cmd>nohlsearch<CR>')

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
-- note: overwrites select mode
vim.keymap.set({'n', 'v'}, 'gh', '^', { desc = "Go to line start" })
vim.keymap.set({'n', 'v'}, 'gl', '$', { desc = "Go to line end" })

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
	local out = vim.system({'remote-git-url', file, line}, {text=true}):wait()
	if out.stderr then
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
if not vim.g.lazy_did_setup then
	local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
	vim.opt.rtp:prepend(lazypath)

	require("lazy").setup({
		'tpope/vim-obsession',
		'numToStr/Comment.nvim',
		'Shatur/neovim-ayu',
		'nvim-lua/plenary.nvim', 'nvim-telescope/telescope.nvim',
		'kosayoda/nvim-lightbulb',
		'echasnovski/mini.nvim', "folke/which-key.nvim",
		'lewis6991/gitsigns.nvim',
		{ "chrisgrieser/nvim-spider", lazy = true },
		{ 'vxpm/rust-expand-macro.nvim', lazy = true },
		-- 'mg979/vim-visual-multi',
		-- 'jokajak/keyseer.nvim',
	}, { install = { missing = true }, rocks = { enabled = false } })
end

require('Comment').setup()
vim.keymap.set('n', '<C-_>', 'gcc', {remap = true})
vim.keymap.set('n', '<C-c>', 'gcc', {remap = true})
-- TODO: find a way to only comment out the selected region
-- using blockwise comments doesn't work in all filetypes
vim.keymap.set('v', '<C-_>', 'gc', {remap = true})
vim.keymap.set('v', '<C-c>', 'gc', {remap = true})

-- TODO: this makes it very hard to see trailing characters
vim.cmd.colorscheme 'ayu-evolve'

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

require('mini.icons').setup()
require('which-key').setup({preset = 'helix', delay = 150, icons = {mappings = false}})

require('gitsigns').setup({ signs = {
	add = { text = '+' },
        change = { text = '~' },
        --[[ delete = { text = '_' },
        topdelete = { text = '‾' }, ]]
        changedelete = { text = '~' },
}})

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

-- vim.g.VM_leader = ','

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
-- use K instead of ' k' for hover

local lsp_mapping = {
	["c"] = "clangd",
	["cpp"] = "clangd",
	["rust"] = "rust-analyzer",
}

vim.api.nvim_create_autocmd('FileType', { callback = function() 
	local provider = lsp_mapping[vim.fn.expand("<amatch>")]
	if (provider) then
		vim.lsp.start({ name = provider, cmd = {provider}, root_dir = vim.fs.root(0, {'.git'}) })
	end
end })

local expand_macro = require('rust-expand-macro').expand_macro
vim.api.nvim_create_user_command('ExpandMacro', expand_macro, {desc = "Expand macro recursively"})

-- needs nvim 11
--[[ vim.lsp.enable("clangd")  -- this can replace `create_autocmd(FileType)` above
-- vim.api.nvim_create_autocmd('LspNotify', {
  callback = function(args)
    if args.data.method == 'textDocument/didOpen' then
      vim.lsp.foldclose('imports', vim.fn.bufwinid(args.buf))
    end
  end,
} )]]
