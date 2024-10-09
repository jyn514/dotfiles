#Requires AutoHotkey v2.0
#SingleInstance Force
	
; FileCreateShortcut "%A_ScriptFullPath%", "%A_Startup%\keybindings.lnk"
; hit "paste shortcut" in ctrl+r `shell:startup` to run this on login

#t::{
; TODO: preserve current dir https://www.reddit.com/r/AutoHotkey/comments/176itsk/launch_terminal_in_current_directory/
RunWait 'wt.exe'
Sleep 1000
WinActivate	"ahk_exe WindowsTerminal.exe"
}

#Esc::DllCall("LockWorkStation")
#-::WinMinimize "A"

SetNumLockState("AlwaysOn")

; #Tab::Send "!{Tab}

; https://www.autohotkey.com/board/topic122581-need-some-help-with-a-window-switching-script/?p=691584
; #Tab::Send "!{Esc}"
toggle := 1
#Tab::{
	global toggle 
	if toggle {
		Send "!{Esc}" 
	} else {
		Send "!+{Esc}"
	}
	toggle := !toggle
	; Send % (toggle:=!toggle)?"!{Esc}":"!+{Esc}" %
}
