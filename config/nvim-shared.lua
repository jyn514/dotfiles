-- Plugin-free behavior shared by normal Neovim and the hardened host editor.
vim.g.mapleader = ' '
vim.g.maplocalleader = 'f'

vim.opt.ignorecase = true
vim.opt.wildignorecase = true
vim.opt.smartcase = true
vim.opt.scrolloff = 3
vim.opt.sidescrolloff = 10
vim.opt.visualbell = true
vim.opt.shiftround = true
vim.opt.termguicolors = true
vim.opt.number = true
vim.opt.breakindent = true
vim.opt.list = true
vim.opt.listchars = { tab = '│ ', trail = '·', nbsp = '␣' }
vim.opt.inccommand = 'split'
vim.opt.textwidth = 0

vim.keymap.set('n', 'n', '/<CR>')
vim.keymap.set('n', 'N', '?<CR>')
vim.keymap.set('n', '<Esc>', function()
	local found_float = false
	for _, window in ipairs(vim.api.nvim_list_wins()) do
		if vim.api.nvim_win_get_config(window).relative ~= '' then
			vim.api.nvim_win_close(window, true)
			found_float = true
		end
	end
	if not found_float then
		vim.cmd.nohlsearch()
	end
end)

vim.keymap.set('n', '<A-h>', '<C-w><C-h>', { desc = 'Move focus to the left window' })
vim.keymap.set('n', '<A-l>', '<C-w><C-l>', { desc = 'Move focus to the right window' })
vim.keymap.set('n', '<A-j>', '<C-w><C-j>', { desc = 'Move focus to the lower window' })
vim.keymap.set('n', '<A-k>', '<C-w><C-k>', { desc = 'Move focus to the upper window' })
vim.keymap.set('n', '<A-z>', '<C-w>_', { desc = 'Maximize the current window' })
vim.keymap.set('n', 'gqq', 'gww', { desc = 'Only format selection, not sentence' })
vim.keymap.set('n', '<A-i>', 'i_<Esc>r', { desc = 'Insert a single character' })
vim.keymap.set('', '<S-ScrollWheelDown>', '5zl', { desc = 'Scroll right' })
vim.keymap.set('', '<S-ScrollWheelUp>', '5zh', { desc = 'Scroll left' })
vim.keymap.set('', '<A-ScrollWheelDown>', '<C-d>', { desc = 'Scroll page down' })
vim.keymap.set('', '<A-ScrollWheelUp>', '<C-u>', { desc = 'Scroll page up' })
vim.keymap.set({ 'i', 'c' }, '<C-e>', '<End>', { desc = 'End' })
vim.keymap.set({ 'i', 'c' }, '<C-a>', '<Home>', { desc = 'Home' })
vim.keymap.set('n', 'U', '<C-r>', { desc = 'Redo' })
vim.keymap.set('n', 'ga', ':b#<CR>', { desc = 'Go to most recently used buffer' })
vim.keymap.set('n', 'gn', ':bnext<CR>', { desc = 'Go to next buffer' })
vim.keymap.set('n', 'gp', ':bprevious<CR>', { desc = 'Go to previous buffer' })
vim.keymap.set({ 'n', 'v' }, 'gh', '^', { desc = 'Go to line start' })
vim.keymap.set({ 'n', 'v' }, 'gl', '$', { desc = 'Go to line end' })
vim.keymap.set('i', '<M-f>', '◊', { desc = 'Lozenge' })
vim.keymap.set('i', '\\l', '◊', { desc = 'Lozenge' })
vim.keymap.set('i', '\\p', '⚘', { desc = 'Petal' })
vim.keymap.set('i', '\\j', '«', { desc = 'Sunflower open quote' })
vim.keymap.set('i', '\\k', '»', { desc = 'Sunflower close quote' })
vim.keymap.set('i', '\\f', '⚘', { desc = 'Floret' })

vim.keymap.set('i', '<Tab>', function()
	local byte_col = vim.fn.getcurpos()[3] - 1
	local display_col = vim.fn.virtcol('.') - 1
	local ws = vim.regex('^\\s*$')
	local line = vim.fn.getline('.'):sub(1, byte_col)
	if ws:match_str(line) then
		return '<Tab>'
	end
	local sw = vim.fn.shiftwidth()
	local width = sw - (display_col % sw)
	return vim.fn['repeat'](' ', width)
end, { expr = true, desc = "Don't insert hard tabs in the middle of lines" })
