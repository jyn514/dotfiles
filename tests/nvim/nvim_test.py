#!/usr/bin/env python3

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
NVIM_CONFIG = ROOT / "config/nvim/init.lua"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
PLUGINS = Path(os.environ.get("DOTFILES_TEST_NVIM_PLUGINS") or DATA / "nvim/lazy")


@unittest.skipUnless(shutil.which("nvim"), "Neovim is not installed")
@unittest.skipUnless(
    (PLUGINS / "lazy.nvim/lua/lazy/init.lua").is_file(),
    "Neovim plugins are not installed",
)
class NeovimConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="nvim-test-plugins-")
        cls.addClassCleanup(temporary.cleanup)
        cls.plugins = Path(temporary.name) / "lazy"
        # Lazy can write plugin metadata; never point it at installed checkouts.
        shutil.copytree(PLUGINS, cls.plugins, ignore=shutil.ignore_patterns(".git"))

    def run_nvim(
        self, lua: str | Path, *, case: str = "", startup_commands: tuple[str, ...] = ()
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = root / "config/nvim"
            work = root / "work"
            config.mkdir(parents=True)
            work.mkdir()
            data = root / "data/nvim"
            data.mkdir(parents=True)
            (data / "lazy").symlink_to(self.plugins)
            (config / "init.lua").symlink_to(NVIM_CONFIG)
            (config / "shared.lua").symlink_to(NVIM_CONFIG.parent / "shared.lua")
            script = root / "test.lua"
            script.write_text(lua.read_text() if isinstance(lua, Path) else lua)

            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(root / "config")
            env["XDG_DATA_HOME"] = str(root / "data")
            env["HOME"] = str(root / "home")
            env["DOTFILES_NVIM_CASE"] = case
            env["DOTFILES_NVIM_TEST_SCRIPT"] = str(script)
            result = subprocess.run(
                [
                    "nvim",
                    "--headless",
                    "--cmd",
                    "let g:fzf_lua_server = 'disabled-in-tests'",
                    *(arg for command in startup_commands for arg in ("--cmd", command)),
                    "-c",
                    f"luafile {Path(__file__).with_name('fixtures') / 'run_test.lua'}",
                    "-c",
                    "qa!",
                ],
                cwd=work,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            return result

    def test_query_definition_follows_each_buffer_checkout_not_editor_cwd(self) -> None:
        self.run_nvim(
            Path(__file__).with_name("fixtures") / "query_definition.lua",
            # Neovim 0.11.1 lacks the grt default removed by init.lua. Supply it
            # so that unrelated E31 does not prevent this focused regression.
            # The other tests retain their unmodified startup diagnostic check.
            startup_commands=("nnoremap grt <Nop>",),
        )

    def test_flix_run_main_uses_client_root_without_changing_editor_cwd(self) -> None:
        fixtures = Path(__file__).with_name("fixtures")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / "bin"
            binaries.mkdir()
            executable = binaries / "flix"
            shutil.copyfile(fixtures / "flix_run.sh", executable)
            executable.chmod(0o755)
            environment = os.environ.copy()
            for key in (
                "NVIM", "NVIM_LISTEN_ADDRESS", "VIMINIT", "EXINIT", "VIM", "VIMRUNTIME",
                "LUA_PATH", "LUA_CPATH", "LUA_INIT", "ENV", "BASH_ENV", "ZDOTDIR", "SHINIT",
            ):
                environment.pop(key, None)
            environment.update({
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "SHELL": "/bin/sh", "NVIM_APPNAME": "nvim",
                "DOTFILES_NVIM_FLIX_CWD_LOG": str(root / "executed-cwd"),
            })
            with patch.dict(os.environ, environment, clear=True):
                self.run_nvim(
                    fixtures / "flix_execution.lua",
                    # Same focused grt compatibility fixture as the query test;
                    # do not suppress startup diagnostics in the other tests.
                    startup_commands=("nnoremap grt <Nop>",),
                )

    def test_config_loads_fzf_without_starting_its_rpc_server(self) -> None:
        self.run_nvim(
            """
assert(type(FzfLua) == 'table')
assert(vim.g.fzf_lua_server == 'disabled-in-tests')
"""
        )

    def test_tab_alignment_uses_display_columns(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "profile_behavior.lua", case="tab-alignment")

    def test_buffer_delete_keeps_loaded_alternate_with_special_filename(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "profile_behavior.lua", case="alternate-buffer")

    def test_daily_journal_uses_the_date_at_each_invocation(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "profile_behavior.lua", case="journal")

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

    def test_move_comment_up_uses_python_syntax_to_skip_strings(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "move_comment.lua", case="python")

    def test_move_comment_up_preserves_multiline_context_outside_range(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "move_comment.lua", case="python-boundary")

    def test_move_comment_up_uses_c_syntax_to_skip_strings(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "move_comment.lua", case="c")

    def test_move_comment_up_preserves_commentstring_only_fallback(self) -> None:
        self.run_nvim(Path(__file__).with_name("fixtures") / "move_comment.lua", case="fallback")

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
assert(vim.v.errmsg == '', vim.v.errmsg)
assert(vim.api.nvim_get_current_tabpage() == first)
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

    def test_lsp_attach_uses_current_codelens_api(self) -> None:
        self.run_nvim(
            """
local enabled
vim.lsp.codelens.refresh = function() error('deprecated codelens API called') end
vim.lsp.codelens.enable = function(value, filter)
  enabled = { value = value, filter = filter }
end
vim.lsp.get_client_by_id = function()
  return { server_capabilities = { codeLensProvider = true } }
end

local bufnr = vim.api.nvim_get_current_buf()
vim.api.nvim_exec_autocmds('LspAttach', { buffer = bufnr, data = { client_id = 1 } })
assert(enabled.value == true)
assert(enabled.filter.bufnr == bufnr)
"""
        )


if __name__ == "__main__":
    unittest.main()
