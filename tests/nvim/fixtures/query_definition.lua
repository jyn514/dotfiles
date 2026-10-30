local base = vim.fn.getcwd()
local a = base .. '/rust-A'
local b = base .. '/rust-B'
local missing_compiler = base .. '/missing-compiler'
local plain_crate = base .. '/plain-crate'
local function write(path, lines)
	vim.fn.mkdir(vim.fs.dirname(path), 'p')
	vim.fn.writefile(lines, path)
end
for _, root in ipairs({ a, b }) do
	write(root .. '/x.py', { '# Rust bootstrap entrypoint' })
	write(root .. '/Cargo.toml', { '[workspace]' })
	write(root .. '/compiler/rustc_query_impl/Cargo.toml', { '[package]' })
	write(root .. '/compiler/rustc_query_impl/src/lib.rs', { 'target_query' })
end
write(a .. '/compiler/rustc_middle/providers.rs', { 'providers.target_query = SOURCE_A;' })
write(a .. '/compiler/rustc_query_impl/local.rs', { 'providers.target_query = CRATE_A;' })
write(a .. '/compiler/rustc_span/src/symbol.rs', { 'providers.target_query = EXCLUDED;' })
write(a .. '/outside.rs', { 'providers.target_query = OUTSIDE_COMPILER;' })
write(b .. '/compiler/foreign.rs', { 'providers.target_query = SOURCE_B;' })
write(missing_compiler .. '/x.py', { '# Rust bootstrap entrypoint' })
write(missing_compiler .. '/src/lib.rs', { 'target_query' })
write(plain_crate .. '/Cargo.toml', { '[package]' })
write(plain_crate .. '/compiler/decoy.rs', { 'providers.target_query = NOT_RUST;' })
write(plain_crate .. '/src/lib.rs', { 'target_query' })

local records = {}
local notifications = {}
vim.notify = function(message, level)
	notifications[#notifications + 1] = {
		message = message, level = level,
		buffer = vim.api.nvim_buf_get_name(0), editor_cwd = vim.fn.getcwd(),
	}
end
local core = require('fzf-lua.core')
local make_entry = require('fzf-lua.make_entry')
-- Keep the loaded mapping, live_grep provider, option normalization and rg
-- generator native. Only replace the interactive terminal with native search.
core.fzf_live = function(_, opts)
	local command = make_entry.get_grep_cmd(opts, opts.search, true)
	local result = vim.system({ 'sh', '-c', command }, { cwd = opts.cwd, text = true }):wait()
	records[#records + 1] = {
		buffer = vim.api.nvim_buf_get_name(0), editor_cwd = vim.fn.getcwd(),
		picker_cwd = opts.cwd, command = command,
		code = result.code, stdout = result.stdout, stderr = result.stderr,
	}
	assert(result.code == 0, result.stderr)
end
local mapping = vim.fn.maparg('gqd', 'n', false, true)
assert(type(mapping.callback) == 'function', 'gqd mapping is missing')
local function edit(path)
	vim.cmd('noautocmd edit ' .. vim.fn.fnameescape(path))
	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	assert(vim.fn.expand('<cword>') == 'target_query')
end
local function cd(path)
	vim.cmd('noautocmd cd ' .. vim.fn.fnameescape(path))
end
local function invoke(expected_root, source, absent)
	local before = #records
	vim.api.nvim_feedkeys('gqd', 'xt', false)
	assert(#records == before + 1, 'gqd did not reach native search')
	local record = records[#records]
	assert(record.picker_cwd == expected_root .. '/compiler', vim.inspect(record))
	assert(record.stdout:find(source, 1, true), vim.inspect(record))
	assert(not record.stdout:find(absent, 1, true), vim.inspect(record))
	assert(not record.stdout:find('EXCLUDED', 1, true), vim.inspect(record))
	assert(not record.stdout:find('OUTSIDE_COMPILER', 1, true), vim.inspect(record))
end
edit(a .. '/compiler/rustc_query_impl/src/lib.rs')
for _, cwd in ipairs({ a, a .. '/compiler/rustc_query_impl', b }) do
	cd(cwd)
	invoke(a, 'SOURCE_A', 'SOURCE_B')
	assert(records[#records].stdout:find('CRATE_A', 1, true))
end
-- A new source buffer must change the selection in the same editor process.
edit(b .. '/compiler/rustc_query_impl/src/lib.rs')
cd(a)
invoke(b, 'SOURCE_B', 'SOURCE_A')
assert(#notifications == 0, vim.inspect(notifications))

local function reject(path)
	if path then
		edit(path)
	else
		vim.cmd('noautocmd enew')
	end
	local before = #records
	local notified = #notifications
	vim.api.nvim_feedkeys('gqd', 'xt', false)
	assert(#records == before, 'invalid source launched a picker')
	assert(#notifications == notified + 1, 'invalid source did not report an error')
	local notification = notifications[#notifications]
	assert(notification.level == vim.log.levels.ERROR, vim.inspect(notification))
	assert(notification.message:find('Rust checkout', 1, true), vim.inspect(notification))
end
-- Valid ambient cwd must never rescue an invalid source buffer.
cd(a)
reject(plain_crate .. '/src/lib.rs')
reject(missing_compiler .. '/src/lib.rs')
reject(nil)
print(vim.json.encode({ cases = records, rejected = notifications }))
