"""Disposable client adapter; production socket paths stay untouched."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("private_desktop", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    sys.exit(module.launch("fixture", sys.argv[3:], Path(sys.argv[2])))
except (OSError, ValueError) as error:
    sys.exit(f"private-desktop: {error}")
