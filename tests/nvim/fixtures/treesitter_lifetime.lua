local runtime_file = vim.api.nvim_get_runtime_file
for _, lang in ipairs({ 'c', 'lua' }) do
	if #runtime_file('parser/' .. lang .. '.*', false) == 0 then
		print('SKIP_TREESITTER_LIFETIME_PARSERS')
		return
	end
end
-- Model C becoming installed on completion without modifying installed parsers.
-- Other runtime lookups, parser loading, attachment and parsing remain native.
local installed
vim.api.nvim_get_runtime_file = function(name, all)
	if name == 'parser/c.*' and not installed then return {} end
	return runtime_file(name, all)
end
local queued
require('nvim-treesitter').install = function(languages)
	assert(languages == 'c', vim.inspect(languages))
	local task = {}
	queued[#queued + 1] = task
	function task:await(callback) self.complete = callback end
	return task
end
vim.treesitter.language.register('c', 'lifetime_c_alias')
for lang, root in pairs({ c = 'translation_unit', lua = 'chunk' }) do
	vim.treesitter.query.set(lang, 'highlights', '(' .. root .. ') @lifetime_root')
	vim.treesitter.query.set(lang, 'injections', '')
end
local native_start = vim.treesitter.start
local native_add = vim.treesitter.language.add
local report
vim.treesitter.language.add = function(lang, ...)
	report.language_adds[#report.language_adds + 1] = lang
	return native_add(lang, ...)
end
vim.treesitter.start = function(buf, lang)
	local attachment = { buffer = buf, requested_lang = lang }
	report.attachments[#report.attachments + 1] = attachment
	local ok, error = pcall(native_start, buf, lang)
	attachment.ok = ok
	if not ok then attachment.error = tostring(error); return assert(ok, error) end
	-- Force parsing through the public API for headless capture observation.
	-- The same lang retrieves the parser just selected by native start.
	local parser = assert(vim.treesitter.get_parser(buf, lang))
	local trees = parser:parse()
	attachment.parser_lang = parser:lang()
	attachment.root_type = trees[1]:root():type()
end
local function filetype(buf, ft, trigger)
	vim.api.nvim_buf_call(buf, function()
		vim.cmd('noautocmd setlocal filetype=' .. ft)
		if trigger ~= false then
			vim.api.nvim_exec_autocmds('FileType', { group = 'dotfiles_config', buffer = buf })
		end
	end)
end
local function capture_language(buf)
	local captures = vim.treesitter.get_captures_at_pos(buf, 0, 0)
	assert(#captures > 0, 'native highlighter has no captures')
	local lang = captures[1].lang
	for _, capture in ipairs(captures) do assert(capture.lang == lang) end
	return lang
end
local results = {}
for _, case in ipairs({ 'unchanged', 'wiped', 'changed-language', 'same-language-alias', 'unloaded', 'installed' }) do
	report = { case = case, attachments = {}, language_adds = {} }
	results[#results + 1] = report
	installed = case == 'installed'
	queued = {}
	local buf = vim.api.nvim_create_buf(true, false)
	vim.api.nvim_set_current_buf(buf)
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'int value = 1;' })
	local ok, error = xpcall(function()
		if case == 'unloaded' then
			local path = vim.fn.getcwd() .. '/unloaded.c'
			vim.api.nvim_buf_set_name(buf, path)
			vim.fn.writefile({ 'int value = 1;' }, path)
		end
		filetype(buf, 'c')
		if case == 'installed' then
			assert(#queued == 0, 'installed parser unexpectedly requested installation')
			report.final_capture = capture_language(buf)
			assert(report.final_capture == 'c')
			return
		end
		assert(#queued == 1 and queued[1].complete, 'FileType did not await installation')
		assert(#report.attachments == 0, 'parser attached before completion')
		if case == 'wiped' then
			vim.api.nvim_buf_delete(buf, { force = true })
		elseif case == 'changed-language' then
			vim.api.nvim_buf_set_lines(buf, 0, -1, false, { 'value = 1' })
			filetype(buf, 'lua')
			report.before_capture = capture_language(buf)
			assert(report.before_capture == 'lua')
		elseif case == 'same-language-alias' then
			filetype(buf, 'lifetime_c_alias', false)
			assert(vim.treesitter.language.get_lang(vim.bo[buf].filetype) == 'c')
		elseif case == 'unloaded' then
			vim.api.nvim_buf_delete(buf, { unload = true, force = true })
			assert(vim.api.nvim_buf_is_valid(buf) and not vim.api.nvim_buf_is_loaded(buf))
		end
		report.loaded_before_completion = vim.api.nvim_buf_is_loaded(buf)
		local added_before = #report.language_adds
		installed = true
		local completed, completion_error = pcall(queued[1].complete, nil, true)
		report.completion_ok = completed
		report.completion_error = not completed and tostring(completion_error) or vim.NIL
		report.loaded_after_completion = vim.api.nvim_buf_is_loaded(buf)
		assert(completed, completion_error)
		if case == 'wiped' or case == 'unloaded' then
			assert(#report.language_adds == added_before, 'stale completion tried loading a language')
			assert(not vim.api.nvim_buf_is_loaded(buf), 'stale completion reloaded the buffer')
			assert(#report.attachments == 0, 'stale completion tried attaching a parser')
		elseif case == 'changed-language' then
			report.after_old_completion = capture_language(buf)
			assert(report.after_old_completion == 'lua', 'stale C completion replaced Lua')
			assert(#report.language_adds == added_before, 'stale completion tried loading a language')
			-- A later eligible event is not blocked by the rejected old completion.
			filetype(buf, 'c')
			report.recovery_capture = capture_language(buf)
			assert(report.recovery_capture == 'c')
			assert(#queued == 1, 'available parser requested another installation')
		else
			report.final_capture = capture_language(buf)
			assert(report.final_capture == 'c')
		end
	end, debug.traceback)
	report.ok = ok
	if not ok then report.error = tostring(error) end
	if vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
end
print(vim.json.encode({ cases = results }))
for _, result in ipairs(results) do assert(result.ok, result.error) end
