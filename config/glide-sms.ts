type SmsDraft = {
    number: string;
    recipients?: Array<{ address: string; number: string | null }>;
    body: string | null;
    copied: boolean;
};

// Passed to glide.content.execute: this function must not capture module state.
async function prefill_google_voice(draft: SmsDraft): Promise<boolean> {
    const prefix = "#dotfiles-sms=";
    if (location.origin !== "https://voice.google.com" || !location.hash.startsWith(prefix)) return false;
    // Consume once, before Google Voice changes its route or creates a draft.
    history.replaceState(history.state, "", location.pathname + location.search);
    const visible = (element: Element) => element.getClientRects().length > 0;
    const digits = (text: string) => text.replace(/[^0-9]/g, "");
    const unique = <T extends Element>(elements: T[]): T | undefined => {
        const matches = elements.filter(visible);
        if (matches.length > 1) throw new Error("more than one matching control");
        return matches[0];
    };
    function wait_for<T>(find: () => T | undefined, description: string): Promise<T> {
        return new Promise((resolve, reject) => {
            const observer = new MutationObserver(check);
            const timeout = setTimeout(() => finish(new Error(`couldn't find ${description}`)), 15000);
            function finish(error?: Error, result?: T) {
                observer.disconnect();
                clearTimeout(timeout);
                if (error) reject(error);
                else resolve(result!);
            }
            function check() {
                try {
                    const result = find();
                    if (result !== undefined) finish(undefined, result);
                } catch (error) {
                    finish(error instanceof Error ? error : new Error(String(error)));
                }
            }
            observer.observe(document, { childList: true, subtree: true, attributes: true });
            check();
        });
    }
    const controls = <T extends Element>(selector: string) =>
        Array.from(document.querySelectorAll<T>(selector));
    function wait_until_quiet(root: Element): Promise<boolean> {
        return new Promise((resolve, reject) => {
            let finished = false;
            let quiet: ReturnType<typeof setTimeout>;
            const observer = new MutationObserver(restart);
            const deadline = setTimeout(() => finish(false, new Error("compose form is still changing")), 5000);
            function finish(ready: boolean, error?: Error) {
                if (finished) return;
                finished = true;
                clearTimeout(quiet);
                clearTimeout(deadline);
                observer.disconnect();
                document.removeEventListener("focusin", restart, true);
                document.removeEventListener("keydown", cancel, true);
                document.removeEventListener("pointerdown", cancel, true);
                if (error) reject(error);
                else resolve(ready);
            }
            function restart() {
                if (finished) return;
                clearTimeout(quiet);
                quiet = setTimeout(() => finish(true), 400);
            }
            function cancel(event: Event) {
                if (event.isTrusted) finish(false);
            }
            observer.observe(root, { childList: true, subtree: true, attributes: true, characterData: true });
            document.addEventListener("focusin", restart, true);
            document.addEventListener("keydown", cancel, true);
            document.addEventListener("pointerdown", cancel, true);
            restart();
        });
    }
    function show_notice(message: string) {
        const notice = document.createElement("div");
        notice.setAttribute("role", "alert");
        notice.style.cssText = "position:fixed;top:12px;left:12px;right:12px;z-index:2147483647;padding:16px;background:#fff3cd;color:#332700;border:2px solid #856404";
        notice.textContent = message;
        const dismiss = document.createElement("button");
        dismiss.textContent = "dismiss";
        dismiss.addEventListener("click", () => notice.remove());
        notice.append(" ", dismiss);
        (document.body || document.documentElement).append(notice);
    }
    try {
        const compose = await wait_for(() => unique(controls<HTMLElement>("button, [role=button], a")
            .filter(element => (element.getAttribute("aria-label") || element.textContent || "")
                .replace(/\s+/g, " ").trim().toLowerCase() === "send new message")), "send new message");
        compose.click();
        const recipients = draft.recipients ?? [{ address: draft.number, number: draft.number }];
        if (!recipients.length || recipients.some(recipient => recipient.number === null)) {
            const recipient = await wait_for(() => unique(controls<HTMLInputElement>("div.input-field > input")),
                "recipient field");
            recipient.focus();
            const fallback = draft.body === null ? "" : draft.copied
                ? " the body is on the clipboard." : " clipboard copying failed.";
            if (recipients.length) {
                show_notice("choose recipients manually; Google Voice cannot resolve these telephone parameters: "
                    + recipients.map(recipient => recipient.address).join(", ") + "." + fallback);
            } else if (draft.body !== null) {
                show_notice("choose a recipient before pasting the message body." + fallback);
            }
            return true;
        }
        for (const target of recipients) {
            const number = target.number!;
            const recipient = await wait_for(() => {
                const field = unique(controls<HTMLInputElement>("div.input-field > input"));
                return field?.value === "" ? field : undefined;
            }, "empty recipient field");
            recipient.focus();
            recipient.value = number;
            recipient.dispatchEvent(new Event("input", { bubbles: true }));
            const suggestion = await wait_for(() => {
                const button = unique(controls<HTMLButtonElement>("section#contact-list > button#send-to-button"));
                if (!button || button.disabled) return;
                // The button also contains a screen-reader copy of the number.
                // Read one label so its digits aren't concatenated with that copy.
                const label = button.querySelector(".send-to-label")?.textContent;
                if (!label) return;
                const displayed = digits(label);
                const expected = digits(number);
                const us_local = /^\+1[0-9]{10}$/.test(number) && displayed === expected.slice(1);
                if (displayed !== expected && !us_local) return;
                return button;
            }, "suggestion matching the recipient's number");
            if (recipient.value !== number) throw new Error("recipient changed while prefilling");
            // Confirm only the explicit send-to-number suggestion, never a contact
            // selected by position or a partial match.
            suggestion.click();
        }
        let body = await wait_for(() => unique(controls<HTMLTextAreaElement>(
            "div.message-input-container > textarea.message-input")), "message field");
        if (body.disabled || body.readOnly || body.value !== "") {
            throw new Error("message field is disabled or already contains a draft");
        }
        if (draft.body !== null) {
            body.value = draft.body;
            body.dispatchEvent(new Event("input", { bubbles: true }));
            if (body.value !== draft.body) throw new Error("message field didn't retain the body");
        }
        const filled_body = body.value;
        if (!await wait_until_quiet(body.closest("main, [role=main]") || document.body)) return false;
        const settled_body = unique(controls<HTMLTextAreaElement>("div.message-input-container > textarea.message-input"));
        if (!settled_body || settled_body.disabled || settled_body.readOnly || settled_body.value !== filled_body) {
            throw new Error("message field changed while the form was settling");
        }
        body = settled_body;
        body.focus();
        body.setSelectionRange(body.value.length, body.value.length);
        if (document.activeElement !== body) throw new Error("message field couldn't take focus");
        if (draft.body !== null && !draft.copied) show_notice("message prefilled, but copying to the clipboard failed.");
        return true;
    } catch (error) {
        const fallback = draft.body === null ? "" : draft.copied
            ? " the message body is on the clipboard; check the recipient before pasting."
            : " copying to the clipboard also failed.";
        show_notice(`SMS prefill stopped: ${error instanceof Error ? error.message : String(error)}.${fallback}`);
        return false;
    }
}

glide.autocmds.create("UrlEnter", { hostname: "voice.google.com" }, async ({ url, tab_id }) => {
    const parsed = new URL(url);
    const prefix = "#dotfiles-sms=";
    if (parsed.protocol !== "https:" || parsed.pathname !== "/u/0/messages" || !parsed.hash.startsWith(prefix)) return;
    const draft: SmsDraft = JSON.parse(decodeURIComponent(parsed.hash.slice(prefix.length)));
    const valid_recipients = draft.recipients === undefined
        ? typeof draft.number === "string" && /^\+?[0-9]+$/.test(draft.number)
        : Array.isArray(draft.recipients) && draft.recipients.every(recipient => recipient
            && typeof recipient.address === "string" && (recipient.number === null
                || (typeof recipient.number === "string" && /^\+?[0-9]+$/.test(recipient.number))));
    if (!valid_recipients || (draft.body !== null && typeof draft.body !== "string") || typeof draft.copied !== "boolean") {
        throw new Error("invalid SMS draft payload");
    }
    const focused = await glide.content.execute(prefill_google_voice, { tab_id, args: [draft] });
    if (focused && (await glide.tabs.active()).id === tab_id) {
        await glide.excmds.execute("mode_change insert");
    }
});
