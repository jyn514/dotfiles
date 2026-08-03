on run scriptArguments
	set shareURL to item 1 of scriptArguments
	set apiPath to item 2 of scriptArguments
	set fetchScript to "window.__extractChatResult = null; fetch(" & quoted form of apiPath & ").then(async response => ({ok: response.ok, status: response.status, statusText: response.statusText, body: await response.text()})).then(result => { window.__extractChatResult = result; }).catch(error => { window.__extractChatResult = {ok: false, status: 0, statusText: String(error), body: ''}; });"

	tell application "Safari"
		make new document
		set ownedWindow to front window

		try
			set URL of current tab of ownedWindow to shareURL
			set pageReady to false
			set automationError to ""

			repeat 240 times
				delay 0.25
				try
					set pageReady to do JavaScript "location.hostname === 'claude.ai' && document.readyState !== 'loading'" in current tab of ownedWindow
				on error messageText
					set automationError to messageText
				end try

				if pageReady then exit repeat
			end repeat

			if not pageReady then
				if automationError is not "" then error "Safari JavaScript automation failed: " & automationError
				error "Timed out waiting for the Claude share page"
			end if

			do JavaScript fetchScript in current tab of ownedWindow
			set resultJSON to "null"

			repeat 240 times
				delay 0.25
				set resultJSON to do JavaScript "JSON.stringify(window.__extractChatResult)" in current tab of ownedWindow
				if resultJSON is not "null" and resultJSON is not "" then exit repeat
			end repeat

			if resultJSON is "null" or resultJSON is "" then error "Timed out waiting for the Claude snapshot"
			close ownedWindow
			return resultJSON
		on error messageText number messageNumber
			try
				close ownedWindow
			end try
			error messageText number messageNumber
		end try
	end tell
end run
