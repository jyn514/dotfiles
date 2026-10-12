#!/usr/bin/env python3
import json
import os
import subprocess
import sys

if sys.argv[1:2] == ["config"]:
    raise SystemExit(subprocess.run([os.environ["DOTFILES_REAL_MISE"], *sys.argv[1:]]).returncode)
print(json.dumps(sys.argv[1:]))
raise SystemExit(int(os.environ.get("DOTFILES_INSTALL_EXIT", "0")))
