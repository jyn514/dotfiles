#!/usr/bin/env python3
"""Copy an SMS body before opening a draft for Glide to prefill."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote


def telephone_recipient(value: str) -> dict:
    """Recognize RFC 3966 subscribers; retain parameters Voice cannot resolve."""
    raw_number, *parameters = value.split(";")
    number = unquote(raw_number, errors="strict")
    address = number + ((";" + ";".join(parameters)) if parameters else "")
    compact = re.sub(r"[().-]", "", number)
    if not re.fullmatch(r"\+?[0-9A-Fa-f*#]+", compact):
        raise ValueError("invalid telephone subscriber")
    if compact.startswith("+") and not compact[1:].isdigit():
        raise ValueError("global telephone numbers must contain decimal digits")
    manual = not re.fullmatch(r"\+?[0-9]+", compact)
    seen = set()
    for parameter in parameters:
        name, equals, argument = parameter.partition("=")
        name = name.lower()
        if not re.fullmatch(r"[A-Za-z0-9-]+", name) or name in seen:
            raise ValueError("invalid or duplicate telephone parameter")
        seen.add(name)
        if equals and not re.fullmatch(r"(?:[A-Za-z0-9\-._!~*'()\[\]/:&+$]|%[0-9A-Fa-f]{2})+", argument):
            raise ValueError("invalid telephone parameter value")
        if name == "phone-context":
            domain = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)*[A-Za-z](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.?"
            context = unquote(argument, errors="strict")
            context_number = re.sub(r"[().-]", "", context)
            if not equals or not (re.fullmatch(domain, context) or re.fullmatch(r"\+[0-9]+", context_number)):
                raise ValueError("invalid phone-context")
            # A phone-context is not a dialing prefix. Voice has no API for it.
            manual = True
        elif name == "ext":
            if not equals or not re.fullmatch(r"[0-9().-]+", unquote(argument, errors="strict")):
                raise ValueError("invalid telephone extension")
            manual = True
        elif name == "isub" or name.startswith("m-"):
            if name == "isub" and not equals:
                raise ValueError("missing ISDN subaddress")
            manual = True
    if "ext" in seen and "isub" in seen:
        raise ValueError("a subscriber cannot have both ext and isub")
    return {"address": address, "number": None if manual else compact}


def sms_draft(uri: str) -> dict:
    """Parse RFC 5724 plus recipientless, smsto, and Apple's open URL forms.

    Unknown SMS fields are ignored, body is UTF-8, and + is never a space.
    Contexts, extensions, and mandatory telephone parameters remain explicit
    recipients for manual resolution instead of silently changing the number.
    """
    if re.search(r"%(?![0-9a-fA-F]{2})", uri):
        raise ValueError("invalid percent escape")
    scheme, colon, rest = uri.partition(":")
    if not colon or scheme.lower() not in ("sms", "smsto"):
        raise ValueError("expected sms:NUMBER?body=TEXT")
    recipients, question, query = rest.partition("?")
    apple = recipients.lower() in ("//open", "//open/")
    if recipients.startswith("//") and not apple:
        raise ValueError("only sms://open is supported as an authority form")
    body = None
    addresses = None
    for field in query.split("&") if question else []:
        name, equals, value = field.partition("=")
        if not equals or not re.fullmatch(r"[A-Za-z0-9._~-]+", name):
            raise ValueError("invalid SMS field")
        if name.lower() == "body":
            if body is not None:
                raise ValueError("body must appear only once")
            body = unquote(value, errors="strict")
        elif apple and name.lower() == "addresses":
            if addresses is not None:
                raise ValueError("addresses must appear only once")
            addresses = unquote(value, errors="strict")
    if apple:
        recipients = addresses or ""
    return {"recipients": [telephone_recipient(value) for value in recipients.split(",")]
            if recipients else [], "body": body}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: open-google-voice SMS_URI")
    try:
        draft = sms_draft(sys.argv[1])
        # Configs already loaded in Glide still consume the single-number field.
        # Derive it here so upgrading the launcher doesn't break existing tabs.
        recipients = draft["recipients"]
        draft["number"] = (recipients[0]["number"] or "") if len(recipients) == 1 else ""
        draft["copied"] = False
        if draft["body"] is not None:
            # Publish the fallback before launching the browser, even when its
            # config fails to load or the Google Voice form has changed.
            copy = Path(__file__).resolve().parents[2] / "bin/copy"
            try:
                subprocess.run([str(copy)], input=draft["body"].encode("utf-8"), check=True)
                draft["copied"] = True
            except (OSError, subprocess.CalledProcessError) as error:
                print(f"open-google-voice: clipboard copy failed: {error}; trying prefill", file=sys.stderr)
        fragment = quote(json.dumps(draft, ensure_ascii=False), safe="")
        target = "https://voice.google.com/u/0/messages#dotfiles-sms=" + fragment
        os.execvp("glide-bin", ["glide-bin", "--new-tab", target])
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"open-google-voice: {error}") from error


if __name__ == "__main__":
    main()
