local cases = {
	python = {
		syntax = 'python',
		commentstring = '# %s',
		before = {
			'outside = 1 # untouched',
			'  message = "hello # world"',
			'  message = "hello # world" # actual note',
			"  message = 'hello # world' # single quoted",
			'  message = """hello # world""" # triple quoted',
			[[  message = "hello \" # world" # escaped quote]],
			'  message = "héllo # world" # unicode note',
			'  message = """hello',
			'  # still a string',
			'  world""" # after indented multiline string',
			'message = """hello',
			'world""" # after unindented multiline string',
			'"same line" # standalone expression',
			'  "same line" # indented expression',
			'  # standalone comment',
			'outside = 2 # untouched',
		},
		after = {
			'outside = 1 # untouched',
			'  message = "hello # world"',
			'  # actual note',
			'  message = "hello # world"',
			'  # single quoted',
			"  message = 'hello # world'",
			'  # triple quoted',
			'  message = """hello # world"""',
			'  # escaped quote',
			[[  message = "hello \" # world"]],
			'  # unicode note',
			'  message = "héllo # world"',
			'  message = """hello',
			'  # still a string',
			'  world""" # after indented multiline string',
			'message = """hello',
			'world""" # after unindented multiline string',
			'# standalone expression',
			'"same line"',
			'  # indented expression',
			'  "same line"',
			'  # standalone comment',
			'outside = 2 # untouched',
		},
	},
	['python-boundary'] = {
		syntax = 'python',
		commentstring = '# %s',
		before = { 'message = """hello', 'world""" # note', 'outside = 1 # untouched' },
		after = { 'message = """hello', 'world""" # note', 'outside = 1 # untouched' },
	},
	c = {
		syntax = 'c',
		commentstring = '/* %s */',
		before = {
			'outside(); /* untouched */',
			'  char *message = "hello /* world */";',
			'  char *message = "hello /* world */"; /* actual note */',
			'  char *message = "hello /* world"; /* after open marker */',
			[[  const char *message = "hello \]],
			'    world"; /* after continued string */',
			'  /* earlier',
			'    */ int value; /* after multiline comment */',
			'/* earlier */ int value; /* safe same-line opener */',
			'  /* earlier */ int value; /* safe indented opener */',
			'  "same line"; /* same-line string */',
			'  body /* keep */ tail',
			'  /* standalone comment */',
			'outside(); /* untouched */',
		},
		after = {
			'outside(); /* untouched */',
			'  char *message = "hello /* world */";',
			'  /* actual note */',
			'  char *message = "hello /* world */";',
			'  /* after open marker */',
			'  char *message = "hello /* world";',
			[[  const char *message = "hello \]],
			'    world"; /* after continued string */',
			'  /* earlier',
			'    */ int value; /* after multiline comment */',
			'/* earlier */ int value; /* safe same-line opener */',
			'  /* earlier */ int value; /* safe indented opener */',
			'  /* same-line string */',
			'  "same line";',
			'  body /* keep */ tail',
			'  /* standalone comment */',
			'outside(); /* untouched */',
		},
	},
	fallback = {
		syntax = '',
		commentstring = '# %s',
		before = { 'outside # untouched', '  body # note', '# standalone', 'outside # untouched' },
		after = { 'outside # untouched', '  # note', '  body', '# standalone', 'outside # untouched' },
	},
}

local case = assert(cases[vim.env.DOTFILES_NVIM_CASE])
-- Select shipped regex syntax without FileType: the real config's FileType hook
-- can otherwise install Tree-sitter grammars over the network in this fixture.
vim.bo.syntax = case.syntax
vim.bo.commentstring = case.commentstring
vim.api.nvim_buf_set_lines(0, 0, -1, false, case.before)
vim.api.nvim_win_set_cursor(0, { 2, 0 })
local view = vim.fn.winsaveview()
vim.cmd(('2,%dMoveCommentUp'):format(#case.before - 1))
local actual = vim.api.nvim_buf_get_lines(0, 0, -1, false)
assert(vim.deep_equal(actual, case.after), vim.inspect(actual))
assert(vim.deep_equal(vim.fn.winsaveview(), view), 'view changed')
