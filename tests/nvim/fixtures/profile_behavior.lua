local case = vim.env.DOTFILES_NVIM_CASE

if case == 'tab-alignment' then
	local mapping = vim.fn.maparg('<Tab>', 'i', false, true)
	assert(type(mapping.callback) == 'function')
	vim.bo.shiftwidth = 4
	vim.bo.tabstop = 8
	for _, row in ipairs({
		{ 'aTAIL', 1, '   ' },
		{ '猫TAIL', 3, '  ' },
		{ 'a\tTAIL', 2, '    ' },
		{ '  TAIL', 2, '<Tab>' },
	}) do
		vim.api.nvim_buf_set_lines(0, 0, -1, false, { row[1] })
		vim.api.nvim_win_set_cursor(0, { 1, row[2] })
		assert(mapping.callback() == row[3], row[1])
	end
elseif case == 'alternate-buffer' then
	vim.cmd('silent! %bwipeout!')
	local names = { 'keep [one].txt', 'keep | two #.txt', 'delete.txt' }
	local buffers = {}
	for _, name in ipairs(names) do
		vim.cmd.enew()
		vim.api.nvim_buf_set_name(0, vim.fn.getcwd() .. '/' .. name)
		table.insert(buffers, vim.api.nvim_get_current_buf())
	end
	vim.cmd.BufferDelete()
	assert(not vim.api.nvim_buf_is_loaded(buffers[3]), 'target buffer was not deleted')
	assert(vim.api.nvim_get_current_buf() ~= buffers[3])
	local alternate = vim.fn.bufnr('#')
	assert(alternate == buffers[1] or alternate == buffers[2], 'alternate buffer was lost')
	assert(vim.api.nvim_buf_is_loaded(alternate))
	assert(vim.api.nvim_get_current_buf() ~= alternate)
elseif case == 'journal' then
	local original_date = os.date
	for _, date in ipairs({ '2040-03-04', '2040-03-05' }) do
		os.date = function(format)
			if format == '%Y-%m-%d' then return date end
			return original_date(format)
		end
		vim.cmd.EditDailyJournal()
		local expected = vim.fn.expand('~/Documents/notes/journal/') .. date .. '.md'
		assert(vim.api.nvim_buf_get_name(0) == expected, 'journal date was cached at startup')
	end
	os.date = original_date
else
	error('unknown Neovim behavior case: ' .. tostring(case))
end
