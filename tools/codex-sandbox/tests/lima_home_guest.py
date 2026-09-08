"""Assert container isolation when the VM itself can access the host home."""

import os
from pathlib import Path


assert not Path(os.environ["HOST_ONLY_FILE"]).exists(), "host home leaked into the container"
assert Path("/src/dotfiles/live.txt").read_text() == "host edit"
Path("/src/dotfiles/written.txt").write_text("container edit")
assert Path("/src/dotfiles/.git/config").read_text() == "protected metadata"
try:
    Path("/src/dotfiles/.git/config").write_text("changed")
except OSError:
    pass
else:
    raise AssertionError("repository metadata became writable")
print(f"uid {os.getuid()}: narrow container mounts preserved under the broad VM share")
