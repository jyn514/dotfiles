-- Hardened configuration for editing untrusted sandbox text on the host.
vim.opt.loadplugins = false
vim.opt.modeline = false
vim.opt.exrc = false
vim.opt.secure = true
vim.opt.swapfile = false
vim.opt.undofile = false
vim.opt.shadafile = 'NONE'

local source = debug.getinfo(1, 'S').source
local config = vim.fs.dirname(source:sub(2))
dofile(config .. '/shared.lua')

-- Load only the trusted color scheme, without running the package's plugin files.
vim.opt.runtimepath:prepend(vim.fn.stdpath('data') .. '/lazy/alabaster.nvim')
local theme_loaded = pcall(vim.cmd.colorscheme, 'alabaster-black')
if not theme_loaded then
	vim.cmd.colorscheme('habamax')
end
