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
write(b .. '/compiler/rustc_query_impl/src/lib.rs', { 'other_query' })
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
-- Observe the mapping's call to the documented picker API. This double does
-- not exercise fzf-lua normalization, command generation, or native search.
require('fzf-lua').live_grep = function(opts)
	records[#records + 1] = {
		buffer = vim.api.nvim_buf_get_name(0), editor_cwd = vim.fn.getcwd(),
		picker_cwd = opts.cwd, search = opts.search, no_esc = opts.no_esc,
	}
end
local mapping = vim.fn.maparg('gqd', 'n', false, true)
assert(type(mapping.callback) == 'function', 'gqd mapping is missing')
local function edit(path, query)
	vim.cmd('noautocmd edit ' .. vim.fn.fnameescape(path))
	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	assert(vim.fn.expand('<cword>') == (query or 'target_query'))
end
local function cd(path)
	vim.cmd('noautocmd cd ' .. vim.fn.fnameescape(path))
end
local function invoke(expected_root, query, absent)
	local before = #records
	vim.api.nvim_feedkeys('gqd', 'xt', false)
	assert(#records == before + 1, 'gqd did not call live_grep')
	local record = records[#records]
	assert(record.picker_cwd == expected_root .. '/compiler', vim.inspect(record))
	assert(type(record.search) == 'string', vim.inspect(record))
	assert(record.search:find(query, 1, true), vim.inspect(record))
	assert(not record.search:find(absent, 1, true), vim.inspect(record))
	assert(record.no_esc == true, vim.inspect(record))
end
edit(a .. '/compiler/rustc_query_impl/src/lib.rs')
for _, cwd in ipairs({ a, a .. '/compiler/rustc_query_impl', b }) do
	cd(cwd)
	invoke(a, 'target_query', 'other_query')
end
-- A new source buffer must change the selection in the same editor process.
edit(b .. '/compiler/rustc_query_impl/src/lib.rs', 'other_query')
cd(a)
invoke(b, 'other_query', 'target_query')
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
