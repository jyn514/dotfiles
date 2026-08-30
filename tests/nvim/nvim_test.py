#!/usr/bin/env python3

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NVIM_CONFIG = ROOT / "config/nvim.lua"
LAZY = Path.home() / ".local/share/nvim/lazy/lazy.nvim"


@unittest.skipUnless(shutil.which("nvim"), "Neovim is not installed")
@unittest.skipUnless(LAZY.exists(), "Neovim plugins are not installed")
class NeovimConfigTests(unittest.TestCase):
    def run_nvim(self, lua: str) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = root / "config/nvim"
            work = root / "work"
            config.mkdir(parents=True)
            work.mkdir()
            (config / "init.lua").symlink_to(NVIM_CONFIG)
            script = root / "test.lua"
            script.write_text(lua)

            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(root / "config")
            result = subprocess.run(
                ["nvim", "--headless", "-c", f"luafile {script}", "-c", "qa!"],
                cwd=work,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)

    def test_buffer_commands_handle_default_ranges_and_invalid_buffers(self) -> None:
        self.run_nvim(
            """
vim.api.nvim_buf_set_lines(0, 0, -1, false, { 'one  ', 'two  ' })
vim.cmd.TrimWhitespace()
assert(vim.deep_equal(vim.api.nvim_buf_get_lines(0, 0, -1, false), { 'one', 'two' }))

vim.cmd.enew()
local unnamed_ok, unnamed_error = pcall(vim.cmd.AutoSave)
assert(not unnamed_ok and unnamed_error:match('named buffer'))

vim.cmd.file('named-buffer')
vim.bo.buftype = 'nofile'
local nonfile_ok, nonfile_error = pcall(vim.cmd.AutoSave)
assert(not nonfile_ok and nonfile_error:match('file buffer'))
"""
        )

    def test_move_comment_up_supports_block_comments(self) -> None:
        self.run_nvim(
            """
vim.bo.commentstring = '/* %s */'
vim.api.nvim_buf_set_lines(0, 0, -1, false, {
  'body /* note */',
  'body /* keep */ tail',
})
vim.cmd('1,2MoveCommentUp')
assert(vim.deep_equal(vim.api.nvim_buf_get_lines(0, 0, -1, false), {
  '/* note */',
  'body',
  'body /* keep */ tail',
}))
"""
        )

    def test_resize_equalizes_every_tabpage(self) -> None:
        self.run_nvim(
            """
local function make_uneven_tab()
  vim.cmd.vsplit()
  vim.cmd('vertical resize 20')
  return vim.api.nvim_get_current_tabpage()
end
local first = make_uneven_tab()
vim.cmd.tabnew()
local second = make_uneven_tab()
vim.api.nvim_set_current_tabpage(first)
vim.api.nvim_exec_autocmds('VimResized', {})
for _, tabpage in ipairs({ first, second }) do
  local widths = {}
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tabpage)) do
    table.insert(widths, vim.api.nvim_win_get_width(win))
  end
  assert(math.abs(widths[1] - widths[2]) <= 1)
end
"""
        )

    def test_custom_lsps_use_native_neovim_registry(self) -> None:
        self.run_nvim(
            """
assert(vim.lsp.config.flix.cmd[1] == 'flix')
assert(vim.lsp.config.rhombus.cmd[1] == 'racket')
assert(vim.lsp.is_enabled('flix'))
assert(vim.lsp.is_enabled('rhombus'))
"""
        )


if __name__ == "__main__":
    unittest.main()
