"""Use the production socket connector without a container runtime."""
import os
from pathlib import Path

connector = Path(__file__).resolve().parents[2] / "image/tool-connect.mjs"
os.execvp("node", ["node", str(connector)])
