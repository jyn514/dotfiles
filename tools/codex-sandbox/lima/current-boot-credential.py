"""Host-owned entrypoint to the installed, generation-pinned credential helper."""

from pathlib import Path
import runpy
import sys

helper, operation, generation, *arguments = sys.argv[1:]
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
# The installed helper independently validates the boot and owns cache access.
sys.argv = [helper, operation, generation, boot, *arguments]
runpy.run_path(helper, run_name='__main__')
