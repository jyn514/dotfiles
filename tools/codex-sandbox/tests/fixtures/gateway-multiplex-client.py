"""Native client: API requests must reuse the master's authenticated connection."""
import http.client
import io
import os
import subprocess
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

host = urlsplit(os.environ['DOCKER_HOST'])
# A fresh connection cannot succeed through /bin/false. Existing multiplexed
# sessions still work, proving that API requests don't reconnect/authenticate.
ssh = ['ssh', '-o', 'ProxyCommand=/bin/false', '-l', unquote(host.username),
       '-p', str(host.port), '--', host.hostname]
for _ in range(3):
    result = subprocess.run([*ssh, 'docker system dial-stdio'],
                            input=b'GET /_ping HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n',
                            capture_output=True, check=True, timeout=10)
    response = http.client.HTTPResponse(SimpleNamespace(makefile=lambda *_: io.BytesIO(result.stdout)))
    response.begin()
    assert response.status == 200 and response.read() == b'OK', result.stdout
print('SSH multiplexed API requests passed.')
