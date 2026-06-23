local wezterm = require("wezterm")
local act = wezterm.action
local mux = wezterm.mux

local config = wezterm.config_builder()
local last_save_at = nil
local probed_save_at = false
local has_resurrect, resurrect = pcall(function()
  return wezterm.plugin.require("https://github.com/YedPool/Wezurrect")
end)

local shell = os.getenv("SHELL") or "zsh"

local function run_shell(command)
  return act.SpawnCommandInNewTab({
    args = { shell, "-lc", command },
    cwd = wezterm.home_dir,
  })
end

local function pane_cwd(pane)
  local uri = pane:get_current_working_dir()
  if not uri then
    return wezterm.home_dir
  end
  if uri.file_path then
    return uri.file_path
  end

  local path = tostring(uri):gsub("^file://[^/]*", "")
  path = path:gsub("%%20", " ")
  return path ~= "" and path or wezterm.home_dir
end

local function run_shell_in_pane_cwd(command)
  return wezterm.action_callback(function(window, pane)
    window:perform_action(act.SpawnCommandInNewTab({
      args = { shell, "-lc", command },
      cwd = pane_cwd(pane),
    }), pane)
  end)
end

local function split_in_pane_cwd(direction)
  return wezterm.action_callback(function(_, pane)
    pane:split({
      direction = direction,
      cwd = pane_cwd(pane),
    })
  end)
end

local function paste_from(args)
  return wezterm.action_callback(function(_, pane)
    local ok, stdout = wezterm.run_child_process(args)
    if ok and stdout and stdout ~= "" then
      pane:send_text(stdout)
    end
  end)
end

local function selected_text()
  local ok, stdout = wezterm.run_child_process({ "paste" })
  if not ok or not stdout then
    return nil
  end
  stdout = stdout:gsub("^%s+", ""):gsub("%s+$", "")
  return stdout ~= "" and stdout or nil
end

local function edit_selected_in_pane()
  return wezterm.action_callback(function(_, pane)
    local text = selected_text()
    if text then
      pane:send_text("${EDITOR:-vi} " .. wezterm.shell_quote_arg(text) .. "\r")
    end
  end)
end

local function trim(text)
  return (text or ""):gsub("^%s+", ""):gsub("%s+$", "")
end

local function url_encode(text)
  return (text:gsub("[^%w%-_%.~]", function(char)
    return string.format("%%%02X", string.byte(char))
  end))
end

local function copy_text(text)
  local quoted = wezterm.shell_quote_arg(text)
  wezterm.run_child_process({
    "sh",
    "-lc",
    "if command -v copy >/dev/null 2>&1; then printf %s " .. quoted .. " | copy; else printf %s " .. quoted .. " | pbcopy; fi",
  })
end

local function open_path(text, cwd)
  wezterm.run_child_process({
    shell,
    "-lc",
    "cd " .. wezterm.shell_quote_arg(cwd) .. " && open " .. wezterm.shell_quote_arg(text),
  })
end

local function selected_text_action(kind)
  return wezterm.action_callback(function(window, pane)
    local text = trim(window:get_selection_text_for_pane(pane))
    if text == "" then
      return
    end

    local choices = {
      { id = "open", label = "open" },
      { id = "copy", label = "copy" },
      { id = "paste", label = "paste" },
      { id = "search", label = "search" },
    }
    if kind == "path" then
      table.insert(choices, { id = "edit", label = "edit" })
    end

    window:perform_action(act.InputSelector({
      title = "Selected " .. kind .. ": " .. text,
      alphabet = "ocpse",
      choices = choices,
      action = wezterm.action_callback(function(_, action_pane, id)
        if not id then
          return
        end
        if id == "open" then
          if kind == "url" then
            wezterm.open_with(text)
          else
            open_path(text, pane_cwd(pane))
          end
        elseif id == "copy" then
          copy_text(text)
        elseif id == "paste" then
          action_pane:send_text(text)
        elseif id == "edit" then
          action_pane:send_text("${EDITOR:-vi} " .. wezterm.shell_quote_arg(text) .. "\r")
        elseif id == "search" then
          wezterm.open_with("https://www.google.com/search?q=" .. url_encode(text))
        end
      end),
    }), pane)
  end)
end

local function select_text_then_choose(kind, pattern)
  return act.QuickSelectArgs({
    label = kind,
    patterns = { pattern },
    action = selected_text_action(kind),
  })
end

local function break_pane()
  return wezterm.action_callback(function(_, pane)
    pane:move_to_new_tab()
  end)
end

local function break_pane_to_window()
  return wezterm.action_callback(function(_, pane)
    pane:move_to_new_window()
  end)
end

local function save_resurrect_state()
  if not has_resurrect then
    return act.ShowDebugOverlay
  end
  return wezterm.action_callback(function()
    resurrect.state_manager.save_workspace_full()
    wezterm.emit("resurrect.save.finished")
  end)
end

local function restore_resurrect_state()
  if not has_resurrect then
    return act.ShowDebugOverlay
  end
  return wezterm.action_callback(function(window, pane)
    resurrect.fuzzy_loader.fuzzy_load(window, pane, function(id)
      local kind = string.match(id, "^([^/]+)")
      local name = string.match(id, "([^/]+)$")
      name = string.match(name, "(.+)%..+$") or name
      local opts = {
        relative = true,
        restore_text = true,
        on_pane_restore = resurrect.tab_state.default_on_pane_restore,
      }
      if kind == "workspace" then
        resurrect.workspace_state.restore_workspace(resurrect.state_manager.load_state(name, "workspace"), opts)
      elseif kind == "window" then
        resurrect.window_state.restore_window(pane:window(), resurrect.state_manager.load_state(name, "window"), opts)
      elseif kind == "tab" then
        resurrect.tab_state.restore_tab(pane:tab(), resurrect.state_manager.load_state(name, "tab"), opts)
      end
    end)
  end)
end

local function probe_last_save_time()
  if probed_save_at or not has_resurrect or not resurrect.state_manager.save_state_dir then
    return nil
  end
  probed_save_at = true

  local current_state = resurrect.state_manager.save_state_dir .. "/current_state"
  local stat_args = { "stat", "-c", "%Y", current_state }
  if wezterm.target_triple:find("apple%-darwin") then
    stat_args = { "stat", "-f", "%m", current_state }
  end
  local ok, stdout = wezterm.run_child_process(stat_args)
  if ok and stdout then
    last_save_at = tonumber(stdout:match("%d+")) or last_save_at
  end
  return last_save_at
end

local function save_age_status()
  local saved_at = last_save_at or probe_last_save_time()
  if not saved_at then
    return ""
  end

  local minutes = math.floor((os.time() - saved_at) / 60)
  return string.format("s=%dm ", minutes)
end

local function cwd_basename(cwd)
  if cwd == wezterm.home_dir then
    return "~"
  end
  return cwd:match("([^/]+)/?$") or cwd
end

local function process_name(pane)
  local ok, name = pcall(pane.get_foreground_process_name, pane)
  if not ok then
    name = nil
  end
  if not name or name == "" then
    local title_ok, title = pcall(pane.get_title, pane)
    return title_ok and title or ""
  end
  return name:match("([^/]+)$") or name
end

local path_pattern = '(?:^|[[:space:]"])(/?(?:(?:~|\\.|\\.\\.)?/)?[A-Za-z0-9_.$#%&+=@"-]+(?:/[A-Za-z0-9_.$#%&+=@"-]+)+(?:[:][0-9]+){0,2})'
local url_pattern = '(?:https?://|git@|git://|ssh://|ftp://|file:///)[^\\s)]+'

if has_resurrect then
  resurrect.setup(config, {
    keybindings = false,
    status_bar = false,
    periodic_interval = 300,
    restore_delay = 3,
    save_workspaces = true,
    save_windows = true,
    save_tabs = true,
    auto_restore_prompt = true,
    retention_days = 7,
  })
else
  wezterm.log_warn("Wezurrect is unavailable: " .. tostring(resurrect))
end

config.font = wezterm.font_with_fallback({
  -- kitty uses "DejaVuSansM Nerd Font Mono", but this WezTerm install
  -- doesn't see that family name through CoreText.
  "JetBrains Mono",
  "Symbols Nerd Font Mono",
})
config.font_size = 14.0

config.color_schemes = {
  Campbell = {
    foreground = "#cccccc",
    background = "#020202",
    cursor_bg = "#ffffff",
    cursor_fg = "#020202",
    cursor_border = "#ffffff",
    selection_fg = "#020202",
    selection_bg = "#ffffff",
    ansi = {
      "#020202",
      "#c50f1f",
      "#13a10e",
      "#f19c00",
      "#0037da",
      "#881798",
      "#3a96dd",
      "#cccccc",
    },
    brights = {
      "#767676",
      "#e74856",
      "#16c60c",
      "#f9f1a5",
      "#3b78ff",
      "#b4009e",
      "#61d6d6",
      "#f2f2f2",
    },
  },
}
config.color_scheme = "Campbell"
config.text_background_opacity = 1.0

config.default_prog = { shell, "-l" }
config.scrollback_lines = 50000
config.enable_kitty_keyboard = true
config.enable_csi_u_key_encoding = true
config.enable_kitty_graphics = true
config.enable_tab_bar = true
config.use_fancy_tab_bar = false
config.hide_tab_bar_if_only_one_tab = false
config.tab_bar_at_bottom = false
config.switch_to_last_active_tab_when_closing_tab = true
config.adjust_window_size_when_changing_font_size = false
config.window_close_confirmation = "NeverPrompt"
config.automatically_reload_config = true
config.status_update_interval = 1000
config.set_environment_variables = {
  COLORTERM = "truecolor",
}
config.selection_word_boundary = " \t\n{}[]()\"'`=,;:"
config.hyperlink_rules = wezterm.default_hyperlink_rules()

config.leader = { key = "k", mods = "CTRL", timeout_milliseconds = 600 }

config.ssh_domains = {
  { name = "home", remote_address = "home", multiplexing = "WezTerm" },
  { name = "linode", remote_address = "linode", multiplexing = "WezTerm" },
  { name = "cloud-dev", remote_address = "cloud-dev", multiplexing = "WezTerm" },
}

-- Built-in QuickSelect already matches URL and path fragments, git hashes,
-- IP addresses, and numbers. Keep the prototype on that path before adding
-- back narrower tmux-style search modes.

config.keys = {
  { key = "c", mods = "SUPER", action = act.CopyTo("Clipboard") },
  { key = "v", mods = "SUPER", action = act.PasteFrom("Clipboard") },
  { key = "v", mods = "CTRL|ALT", action = act.PasteFrom("Clipboard") },
  { key = "Copy", mods = "NONE", action = act.CopyTo("Clipboard") },
  { key = "Paste", mods = "NONE", action = act.PasteFrom("Clipboard") },
  { key = "+", mods = "CTRL|ALT", action = act.Multiple({ act.IncreaseFontSize, act.IncreaseFontSize }) },

  { key = "PageUp", mods = "CTRL", action = act.ActivateTabRelative(-1) },
  { key = "PageDown", mods = "CTRL", action = act.ActivateTabRelative(1) },
  { key = "PageUp", mods = "CTRL|ALT", action = act.MoveTabRelative(-1) },
  { key = "PageDown", mods = "CTRL|ALT", action = act.MoveTabRelative(1) },
  { key = "t", mods = "CTRL|ALT", action = act.SpawnTab("CurrentPaneDomain") },
  { key = "h", mods = "CTRL|ALT", action = act.SpawnCommandInNewTab({ domain = { DomainName = "home" } }) },
  { key = "l", mods = "CTRL|ALT", action = act.SpawnCommandInNewTab({ domain = { DomainName = "linode" } }) },
  { key = "c", mods = "CTRL|ALT", action = act.SpawnCommandInNewTab({ domain = { DomainName = "cloud-dev" }, args = { shell, "-l" } }) },

  { key = "UpArrow", mods = "CTRL|ALT", action = act.ScrollByLine(-1) },
  { key = "DownArrow", mods = "CTRL|ALT", action = act.ScrollByLine(1) },
  { key = "k", mods = "CTRL|ALT", action = act.ScrollByLine(-1) },
  { key = "j", mods = "CTRL|ALT", action = act.ScrollByLine(1) },
  { key = "PageUp", mods = "SHIFT", action = act.ScrollByPage(-1) },
  { key = "PageDown", mods = "SHIFT", action = act.ScrollByPage(1) },
  { key = "r", mods = "CTRL|ALT", action = act.ReloadConfiguration },
  { key = "e", mods = "CTRL|ALT", action = run_shell("$EDITOR ~/.config/wezterm/wezterm.lua") },
  { key = "/", mods = "CTRL|ALT", action = act.Search("CurrentSelectionOrEmptyString") },

  { key = "\\", mods = "LEADER", action = act.SendKey({ key = "k", mods = "CTRL" }) },
  { key = "v", mods = "LEADER", action = act.ActivateCopyMode },
  { key = "[", mods = "LEADER", action = act.ActivateCopyMode },
  { key = "/", mods = "LEADER", action = act.Search("CurrentSelectionOrEmptyString") },
  { key = "?", mods = "LEADER", action = act.ActivateCommandPalette },
  { key = "h", mods = "LEADER", action = act.ActivatePaneDirection("Left") },
  { key = "j", mods = "LEADER", action = act.ActivatePaneDirection("Down") },
  { key = "k", mods = "LEADER", action = act.ActivatePaneDirection("Up") },
  { key = "l", mods = "LEADER", action = act.ActivatePaneDirection("Right") },
  { key = "L", mods = "LEADER", action = split_in_pane_cwd("Right") },
  { key = "J", mods = "LEADER", action = split_in_pane_cwd("Bottom") },
  { key = "H", mods = "LEADER", action = split_in_pane_cwd("Left") },
  { key = "K", mods = "LEADER", action = split_in_pane_cwd("Top") },
  { key = "h", mods = "LEADER|ALT", action = act.AdjustPaneSize({ "Left", 1 }) },
  { key = "j", mods = "LEADER|ALT", action = act.AdjustPaneSize({ "Down", 1 }) },
  { key = "k", mods = "LEADER|ALT", action = act.AdjustPaneSize({ "Up", 1 }) },
  { key = "l", mods = "LEADER|ALT", action = act.AdjustPaneSize({ "Right", 1 }) },
  { key = "h", mods = "LEADER|CTRL", action = act.RotatePanes("CounterClockwise") },
  { key = "j", mods = "LEADER|CTRL", action = act.PaneSelect({ mode = "SwapWithActiveKeepFocus" }) },
  { key = "k", mods = "LEADER|CTRL", action = act.PaneSelect({ mode = "SwapWithActiveKeepFocus" }) },
  { key = "l", mods = "LEADER|CTRL", action = act.RotatePanes("Clockwise") },
  { key = "=", mods = "LEADER", action = act.PaneSelect({ mode = "SwapWithActiveKeepFocus" }) },
  { key = "f", mods = "LEADER|CTRL", action = act.ShowLauncherArgs({ flags = "FUZZY|TABS|WORKSPACES" }) },
  { key = "C", mods = "LEADER", action = act.PromptInputLine({
    description = "New workspace",
    action = wezterm.action_callback(function(_, _, line)
      if line and line ~= "" then
        mux.set_active_workspace(line)
      end
    end),
  }) },
  { key = "N", mods = "LEADER", action = act.SwitchWorkspaceRelative(1) },
  { key = "N", mods = "LEADER|ALT", action = act.SwitchWorkspaceRelative(-1) },
  { key = "t", mods = "LEADER", action = act.SpawnTab("CurrentPaneDomain") },
  { key = "Tab", mods = "LEADER", action = act.ActivateTabRelative(1) },
  { key = "Tab", mods = "LEADER|SHIFT", action = act.ActivateTabRelative(-1) },
  { key = "n", mods = "LEADER|ALT", action = act.ActivateTabRelative(-1) },
  { key = "W", mods = "LEADER", action = break_pane() },
  { key = "W", mods = "LEADER|CTRL", action = break_pane_to_window() },
  { key = "w", mods = "LEADER|ALT", action = act.ShowLauncherArgs({ flags = "FUZZY|TABS" }) },
  { key = "o", mods = "LEADER", action = act.ShowTabNavigator },
  { key = "O", mods = "LEADER", action = act.ShowLauncherArgs({ flags = "FUZZY|WORKSPACES|TABS" }) },
  { key = "w", mods = "LEADER", action = act.CloseCurrentTab({ confirm = true }) },
  { key = "p", mods = "LEADER", action = paste_from({ "paste", "--primary" }) },
  { key = "P", mods = "LEADER", action = paste_from({ "paste" }) },
  { key = "f", mods = "LEADER", action = select_text_then_choose("path", path_pattern) },
  { key = "u", mods = "LEADER", action = select_text_then_choose("url", url_pattern) },
  { key = "g", mods = "LEADER", action = act.QuickSelect },
  { key = "i", mods = "LEADER|ALT", action = act.QuickSelect },
  { key = "r", mods = "LEADER", action = act.ReloadConfiguration },
  { key = "e", mods = "LEADER", action = run_shell("hx-hax ~/.config/wezterm/wezterm.lua") },
  { key = "s", mods = "LEADER|CTRL", action = save_resurrect_state() },
  { key = "r", mods = "LEADER|CTRL", action = restore_resurrect_state() },
}

config.key_tables = {
  copy_mode = {
    { key = "v", mods = "NONE", action = act.CopyMode({ SetSelectionMode = "Cell" }) },
    { key = "y", mods = "NONE", action = act.Multiple({ act.CopyTo("Clipboard"), act.CopyMode("Close") }) },
    { key = "o", mods = "NONE", action = act.Multiple({ act.CopyTo("Clipboard"), run_shell_in_pane_cwd("paste | xargs open") }) },
    { key = "O", mods = "NONE", action = act.Multiple({ act.CopyTo("Clipboard"), edit_selected_in_pane(), act.CopyMode("Close") }) },
    { key = "s", mods = "NONE", action = act.Multiple({ act.CopyTo("Clipboard"), run_shell_in_pane_cwd("paste | xargs -I {} open 'https://www.google.com/search?q={}'") }) },
    { key = "Tab", mods = "NONE", action = act.Multiple({ act.CopyTo("Clipboard"), act.PasteFrom("Clipboard"), act.CopyMode("Close") }) },
    { key = "Home", mods = "NONE", action = act.CopyMode("MoveToScrollbackTop") },
    { key = "End", mods = "NONE", action = act.CopyMode("MoveToScrollbackBottom") },
  },
}

config.mouse_bindings = {
  {
    event = { Down = { streak = 1, button = "Middle" } },
    mods = "NONE",
    action = act.PasteFrom("PrimarySelection"),
  },
  {
    event = { Down = { streak = 1, button = "Right" } },
    mods = "NONE",
    action = act.PasteFrom("Clipboard"),
  },
  {
    event = { Down = { streak = 1, button = "Left" } },
    mods = "ALT",
    action = act.OpenLinkAtMouseCursor,
  },
  {
    event = { Down = { streak = 2, button = "Left" } },
    mods = "ALT",
    action = act.CompleteSelectionOrOpenLinkAtMouseCursor("PrimarySelection"),
  },
}

wezterm.on("resurrect.state_manager.event_driven_save.finished", function()
  last_save_at = os.time()
end)

wezterm.on("resurrect.state_manager.periodic_save.finished", function()
  last_save_at = os.time()
end)

wezterm.on("resurrect.save.finished", function()
  last_save_at = os.time()
end)

wezterm.on("format-tab-title", function(tab)
  local pane = tab.active_pane
  local title = (pane and pane.title) or tab.tab_title or ""
  local cwd = pane and pane.current_working_dir
  if cwd and cwd ~= "" then
    cwd = tostring(cwd):gsub("^file://[^/]*", ""):gsub("%%20", " ")
    title = cwd_basename(cwd) .. " (" .. title .. ")"
  end
  if #title > 30 then
    title = string.sub(title, 1, 27) .. "..."
  end
  return " " .. title .. " "
end)

wezterm.on("update-right-status", function(window, pane)
  local title_ok, title = pcall(pane.get_title, pane)
  if not title_ok then
    return
  end
  if #title > 21 then
    title = string.sub(title, 1, 18) .. "..."
  end
  local prefix = ""
  local ok, active = pcall(window.leader_is_active, window)
  if ok and active then
    prefix = "C-k "
  end
  local cwd_ok, cwd = pcall(pane_cwd, pane)
  if not cwd_ok then
    return
  end
  local proc = process_name(pane)
  window:set_right_status(wezterm.format({
    { Attribute = { Intensity = "Half" } },
    { Text = " " .. prefix .. save_age_status() .. window:active_workspace() .. " " },
    { Foreground = { Color = "#ffffff" } },
    { Background = { Color = "#881798" } },
    { Text = " " .. cwd_basename(cwd) .. " (" .. proc .. ") " .. title .. " " .. wezterm.strftime("%H:%M %d-%b-%y") .. " " },
  }))
end)

return config
