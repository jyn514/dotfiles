-- skeleton comes from https://github.com/nvim-lua/kickstart.nvim/blob/5bdde24dfb353d365d908c5dd700f412ed2ffb17/init.lua

vim.g.mapleader = ' '
vim.g.maplocalleader = ' '
vim.opt.number = true
vim.opt.breakindent = true
vim.opt.undofile = true
vim.opt.ignorecase = true
vim.opt.smartcase = true

vim.opt.list = true
-- tab isn't shown because it's distracting
vim.opt.listchars = { tab = '  ', trail = '·', nbsp = '␣' }
-- shows :s/foo/bar preview live
vim.opt.inccommand = 'split'

-- Clear highlights on search when pressing <Esc> in normal mode
--  See `:help hlsearch`
vim.keymap.set('n', '<Esc>', '<cmd>nohlsearch<CR>')

-- what does this do lol
-- vim.keymap.set('n', '<leader>q', vim.diagnostic.setloclist, { desc = 'Open diagnostic [Q]uickfix list' })

vim.keymap.set('n', '<C-h>', '<C-w><C-h>', { desc = 'Move focus to the left window' })
vim.keymap.set('n', '<C-l>', '<C-w><C-l>', { desc = 'Move focus to the right window' })
vim.keymap.set('n', '<C-j>', '<C-w><C-j>', { desc = 'Move focus to the lower window' })
vim.keymap.set('n', '<C-k>', '<C-w><C-k>', { desc = 'Move focus to the upper window' })

vim.keymap.set('n', '<A-Left>', '<C-o>', { desc = 'Go back in history' })
vim.keymap.set('n', '<A-Right>', '<C-i>', { desc = 'Go forward in history' })

-- add some helix keybinds
vim.keymap.set('n', 'U', '<C-r>', { desc = "Redo" }) -- overwrites "undo line" with no replacement
vim.keymap.set('n', 'ga', ':b#<cr>', { desc = "Go to most recently used buffer" }) -- overwrites `:as[cii]` keybind
vim.keymap.set('n', 'gn', ':bnext<cr>', { desc = "Go to next buffer" }) -- overwrites `nv` keybind
vim.keymap.set('n', 'gp', ':bprevious<cr>', { desc = "Go to previous buffer" }) -- overwrites "paste before cursor"
-- note: overwrites select mode
vim.keymap.set('n', 'gh', '^', { desc = "Go to line start" })
vim.keymap.set('n', 'gl', '$', { desc = "Go to line end" })
-- vim.keymap.set('

-- vim.keymap.set('n', '<leader>b', ':buffers<cr>:buffer ', { desc = "Open buffer picker" })
vim.api.nvim_create_user_command('EditConfig', 'edit ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
vim.api.nvim_create_user_command('ReloadConfig', 'source ' .. vim.fn.stdpath("config") .. '/init.lua', { desc = "edit Lua config" })
-- vim.keymap.
vim.cmd.cabbrev('open', 'edit')
vim.cmd.cabbrev('o', 'edit')

-- disable some warnings
vim.g.loaded_node_provider = 0
vim.g.loaded_perl_provider = 0
vim.g.loaded_ruby_provider = 0

---- LSP ----
vim.keymap.set('n', '<leader>.', function() vim.lsp.buf.code_action() end, { desc = "LSP code action" })
vim.keymap.set('n', 'gd', '<C-]>', { desc = "Goto definition" })
vim.keymap.set('n', 'gD', function() vim.lsp.buf.declaration() end, { desc = "Goto declaration" })
vim.keymap.set('n', 'gr', ':Telescope lsp_references<cr>', { desc = "Find references" })
vim.keymap.set('n', 'gy', ':Telescope lsp_type_definitions<cr>', { desc = "Goto type definition" })

-- `fs.root` is new in nvim 10
function fs_root(files)
     for dir in vim.fs.parents(vim.api.nvim_buf_get_name(0)) do
	for _, rel_file in ipairs(files) do
		local file = dir .. "/" .. rel_file
	       if vim.fn.isdirectory(file) == 1 or vim.fn.filereadable(file) == 1 then
		 return dir
	       end
       end
     end
end

local lsp_mapping = {
	["c"] = "clangd",
	["rust"] = "rust-analyzer",
}

vim.api.nvim_create_autocmd('FileType', { callback = function() 
	local provider = lsp_mapping[vim.fn.expand("<amatch>")]
	if (provider) then
		vim.lsp.start({ name = provider, cmd = {provider}, root_dir = fs_root({'.git'}) })
	end
end })

-- needs nvim 11
--[[ vim.lsp.enable("clangd")  -- this can replace `create_autocmd(FileType)` above
-- vim.api.nvim_create_autocmd('LspNotify', {
  callback = function(args)
    if args.data.method == 'textDocument/didOpen' then
      vim.lsp.foldclose('imports', vim.fn.bufwinid(args.buf))
    end
  end,
} )]]

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
		-- 'mg979/vim-visual-multi',
		-- 'jokajak/keyseer.nvim',
	}, { install = { missing = true }, rocks = { enabled = false } })
end

require('Comment').setup()
vim.keymap.set('n', '<C-_>', 'gcc', {remap = true})
vim.keymap.set('n', '<C-c>', 'gcc', {remap = true})
vim.keymap.set('v', '<C-_>', 'gb', {remap = true})
vim.keymap.set('v', '<C-c>', 'gb', {remap = true})

require('ayu').colorscheme()

vim.keymap.set('n', '<leader>b', ':Telescope buffers<cr>', { desc = "Open buffer picker" })
vim.keymap.set('n', '<leader>f', ':Telescope find_files<cr>', { desc = "Open file picker" })

require("nvim-lightbulb").setup({
  autocmd = { enabled = true }
})

require('mini.icons').setup()
require('which-key').setup({preset = 'helix', delay = 0, icons = {mappings = false}})

-- vim.g.VM_leader = ','
