"""Mark a partial request only after production forwarding has sent its bytes."""

from pathlib import Path
import runpy
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ready = Path(sys.argv[1])


class ObservedSocket(socket.socket):
    def sendall(self, data, *args, **kwargs):
        result = super().sendall(data, *args, **kwargs)
        peer = self.getpeername()
        if isinstance(peer, str) and peer.startswith('/tmp/codex-proxy-') and peer.endswith('/host'):
            ready.write_text('sent')
        return result


with patch.object(socket, 'socket', ObservedSocket):
    router = runpy.run_path(str(ROOT / 'sandbox-proxies.py'))
    raise SystemExit(router['main'](sys.argv[2:]))
