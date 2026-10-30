local base = vim.fn.getcwd()
local a, b = base .. '/project A', base .. '/project B'
local log = assert(vim.env.DOTFILES_NVIM_FLIX_CWD_LOG)
assert(vim.fn.exepath('flix') == vim.fs.dirname(log) .. '/bin/flix')
-- The maintained regression starts at the public configured callback boundary.
-- Native two-client LSP/codelens dispatch is covered by the retained probe;
-- do not start a server or require codelens.enable on old Neovim here.
vim.lsp.enable('flix', false)
local clients, buffers = {}, {}
for index, root in ipairs({ a, b }) do
	vim.fn.mkdir(root .. '/src', 'p')
	vim.fn.writefile({}, root .. (index == 1 and '/flix.toml' or '/flix.jar'))
	local filename = root .. '/src/Main.flix'
	vim.fn.writefile({ '// inert fixture, never compiled' }, filename)
	local buffer = vim.fn.bufadd(filename)
	vim.fn.bufload(buffer)
	local selected
	vim.lsp.config.flix.root_dir(buffer, function(dir) selected = dir end)
	assert(selected == root, vim.inspect({ expected = root, selected = selected }))
	-- Only documented client fields consumed by the configured on_attach.
	local client = { root_dir = selected, commands = {} }
	vim.lsp.config.flix.on_attach(client, buffer)
	clients[index], buffers[index] = client, buffer
end
local function editor_state()
	return {
		cwd = vim.fn.getcwd(), global_cwd = vim.fn.getcwd(-1, -1),
		tab_cwd = vim.fn.getcwd(-1, 0), local_scope = vim.fn.haslocaldir(),
		window = vim.api.nvim_get_current_win(), windows = vim.api.nvim_list_wins(),
		tab = vim.api.nvim_get_current_tabpage(), tabs = vim.api.nvim_list_tabpages(),
	}
end
local function run(index, ambient, local_cwd, exit_status)
	vim.api.nvim_set_current_buf(buffers[index])
	vim.cmd('cd ' .. vim.fn.fnameescape(ambient))
	if local_cwd then vim.cmd('lcd ' .. vim.fn.fnameescape(local_cwd)) end
	vim.env.DOTFILES_NVIM_FLIX_EXIT_STATUS = tostring(exit_status or 0)
	vim.fn.delete(log)
	local before = editor_state()
	clients[index].commands['flix.runMain'](
		{ title = 'Run Main', command = 'flix.runMain' },
		{ bufnr = buffers[index], client_id = index }
	)
	local terminal = vim.api.nvim_get_current_buf()
	assert(terminal ~= buffers[index] and vim.bo.buftype == 'terminal')
	local job = vim.b.terminal_job_id
	assert(type(job) == 'number' and job > 0, 'no native terminal job')
	local status = vim.fn.jobwait({ job }, 5000)[1]
	assert(status == (exit_status or 0), vim.inspect({ exit_status = status }))
	local executed = vim.fn.readfile(log)
	assert(#executed == 1 and executed[1] == clients[index].root_dir,
		vim.inspect({ selected_root = clients[index].root_dir, executed_cwd = executed, editor = before }))
	assert(vim.deep_equal(before, editor_state()), 'terminal changed editor cwd/window/tab state')
	print('Flix terminal: ' .. vim.json.encode({
		client = index, root = clients[index].root_dir, process_cwd = executed[1],
		editor = before, exit_status = status,
	}))
	vim.api.nvim_set_current_buf(buffers[index])
	vim.api.nvim_buf_delete(terminal, { force = true })
end
-- Both handlers are installed first: later attachment must not steal ownership.
run(1, a)
run(1, b)
run(1, base)
run(1, base, a .. '/src')
run(2, a)
run(2, base, a .. '/src')
run(2, a, b .. '/src', 7)
run(1, b, b .. '/src')
assert(vim.v.errmsg == '', vim.v.errmsg)
