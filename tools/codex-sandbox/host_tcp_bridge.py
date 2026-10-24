"""Supervised fixed-destination TCP bridge for a selected host capability."""

from __future__ import annotations

import selectors
import socket
import struct
import threading


def _abortive_close(connection: socket.socket) -> None:
    # A normal FIN after request EOF is indistinguishable from the strict
    # framing half-close. Preserve transport cancellation as an abnormal close
    # even when no response bytes are pending to provoke a failed send.
    try:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    connection.close()


class FixedTcpBridge:
    def __init__(self, target: tuple[str, int], *,
                 listen_address: tuple[str, int] = ("0.0.0.0", 0),
                 allow_all_peers: bool = False,
                 max_connections: int | None = None) -> None:
        if max_connections is not None and max_connections < 1:
            raise ValueError("max_connections must be positive")
        self.target = target
        self.listen_address = listen_address
        self.allow_all_peers = allow_all_peers
        self.max_connections = max_connections
        self.listener: socket.socket | None = None
        self.port: int | None = None
        self.allowed_peers: set[str] = set()
        self.allowed_peers_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.connections: set[socket.socket] = set()
        self.connections_lock = threading.Lock()
        self.workers: set[threading.Thread] = set()
        self.workers_lock = threading.Lock()

    def start(self) -> None:
        # Selection is required authority, not best-effort discovery.
        with socket.create_connection(self.target, timeout=1):
            pass
        listener = socket.socket()
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(self.listen_address)
            listener.listen(16)
            listener.settimeout(0.2)
        except BaseException:
            listener.close()
            raise
        self.listener = listener
        self.port = listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, name="fixed-tcp-bridge", daemon=True)
        self.thread.start()

    def allow_peers(self, peers: set[str]) -> None:
        with self.allowed_peers_lock:
            self.allowed_peers = set(peers)

    def stop(self) -> None:
        self.stop_event.set()
        if self.listener is not None:
            self.listener.close()
        with self.connections_lock:
            connections = list(self.connections)
        for connection in connections:
            _abortive_close(connection)
        if self.thread is not None:
            self.thread.join(timeout=2)
        with self.workers_lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join(timeout=2)

    def _serve(self) -> None:
        assert self.listener is not None
        while not self.stop_event.is_set():
            try:
                connection, address = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self.stop_event.is_set():
                    return
                raise
            with self.allowed_peers_lock:
                allowed = self.allow_all_peers or address[0] in self.allowed_peers
            if not allowed:
                connection.close()
                continue
            worker = threading.Thread(target=self._relay_connection, args=(connection,), daemon=True)
            with self.workers_lock:
                if self.max_connections is not None and len(self.workers) >= self.max_connections:
                    _abortive_close(connection)
                    continue
                self.workers.add(worker)
                # Starting under the lock prevents stop() from observing and
                # joining a reserved-but-not-yet-started capacity slot.
                worker.start()

    def _relay_connection(self, downstream: socket.socket) -> None:
        upstream = None
        abnormal = False
        try:
            if self.stop_event.is_set():
                return
            with self.connections_lock:
                self.connections.add(downstream)
            upstream = socket.create_connection(self.target, timeout=2)
            # Keep each direction independent: framed clients half-close their
            # request stream before reading the response. Bounded nonblocking
            # buffers also let stop interrupt a peer which never drains output.
            downstream.setblocking(False)
            upstream.setblocking(False)
            with self.connections_lock:
                self.connections.update((downstream, upstream))
            peers = {downstream: upstream, upstream: downstream}
            pending = {downstream: bytearray(), upstream: bytearray()}
            reading = {downstream: True, upstream: True}
            write_closed = {downstream: False, upstream: False}
            with selectors.DefaultSelector() as selector:
                while not self.stop_event.is_set():
                    for connection, peer in peers.items():
                        # EOF removes a socket's READ interest, but a later RST
                        # must still cancel its peer while both sides are quiet.
                        # SO_ERROR reports this without a busy EOF-read loop or
                        # sending bytes on the framed protocol. Reading SO_ERROR
                        # clears it, so immediately propagate any nonzero error.
                        error = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if error:
                            raise OSError(error, "TCP peer aborted after request EOF")
                        if not reading[peer] and not pending[connection] and not write_closed[connection]:
                            connection.shutdown(socket.SHUT_WR)
                            write_closed[connection] = True
                        mask = 0
                        if reading[connection] and len(pending[peer]) < 65536:
                            mask |= selectors.EVENT_READ
                        if pending[connection]:
                            mask |= selectors.EVENT_WRITE
                        try:
                            selector.unregister(connection)
                        except KeyError:
                            pass
                        if mask:
                            selector.register(connection, mask)
                    if all(write_closed.values()):
                        return
                    for key, mask in selector.select(0.2):
                        connection = key.fileobj
                        peer = peers[connection]
                        if mask & selectors.EVENT_READ:
                            try:
                                data = connection.recv(65536 - len(pending[peer]))
                            except BlockingIOError:
                                continue
                            if data:
                                pending[peer].extend(data)
                            else:
                                reading[connection] = False
                        if mask & selectors.EVENT_WRITE:
                            try:
                                sent = connection.send(pending[connection])
                            except BlockingIOError:
                                continue
                            if not sent:
                                abnormal = True
                                return
                            del pending[connection][:sent]
        except OSError:
            abnormal = True
            return
        except ValueError:
            # stop may close a socket between selector updates. Do not hide
            # unrelated invalid descriptor/programming failures during service.
            if not self.stop_event.is_set():
                raise
        finally:
            with self.connections_lock:
                self.connections.discard(downstream)
                if upstream is not None:
                    self.connections.discard(upstream)
            if abnormal:
                _abortive_close(downstream)
                if upstream is not None:
                    _abortive_close(upstream)
            else:
                downstream.close()
                if upstream is not None:
                    upstream.close()
            with self.workers_lock:
                self.workers.discard(threading.current_thread())
