local ok, err = xpcall(function()
	assert(vim.v.errmsg == '', vim.v.errmsg)
	dofile(vim.env.DOTFILES_NVIM_TEST_SCRIPT)
end, debug.traceback)
if not ok then
	print(err)
	vim.cmd('cquit 1')
end
