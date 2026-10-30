local result = {
  file = vim.api.nvim_buf_get_name(0),
  cursor = vim.api.nvim_win_get_cursor(0),
  lines = vim.api.nvim_buf_get_lines(0, 0, -1, false),
}
vim.fn.writefile({vim.fn.json_encode(result)}, vim.env.DOTFILES_TEST_NVIM_RESULT)
vim.cmd('qa!')
