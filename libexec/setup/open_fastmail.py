#!/usr/bin/env python3

import os
import sys
from urllib.parse import quote, urlsplit


def fastmail_compose(mailto: str) -> str:
    if urlsplit(mailto).scheme != "mailto":
        raise ValueError("expected a mailto URI")
    return "https://app.fastmail.com/mail/compose?mailto=" + quote(mailto, safe="")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: open-fastmail MAILTO_URI")
    try:
        target = fastmail_compose(sys.argv[1])
    except ValueError as error:
        raise SystemExit(f"open-fastmail: {error}") from error
    os.execvp("xdg-open", ["xdg-open", target])


if __name__ == "__main__":
    main()
