vim.o.background = 'dark'
require('ayu.config').mirage = false

-- actual config
-- adapted from https://github.com/helix-editor/helix/blob/066e938ba083c0259ff411b681eca7bad30980df/runtime/themes/ayu_evolve.toml
local evolve = {
	bg = '#020202',
	black = '#0D0D0D',
	light_gray = "#dedede",
	red = "#DD3E25",
	vibrant_yellow = "#CFCA0D",
	vibrant_orange = "#FF8732",
}

-- what a mess
local colors = require('ayu.colors')
local old_generate = colors.generate
colors.generate = function()
	old_generate()
	for k, v in pairs(evolve) do
		colors[k] = v
	end
end

require('ayu').colorscheme()
