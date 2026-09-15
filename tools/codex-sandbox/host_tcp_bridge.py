"""Supervised fixed-destination TCP bridge for a selected host capability."""

from __future__ import annotations

import selectors
import socket
import threading


class FixedTcpBridge:
    def __init__(self, target: tuple[str, int]) -> None:
        self.target = target
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
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 0))
        listener.listen(16)
        listener.settimeout(0.2)
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
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
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
                allowed = address[0] in self.allowed_peers
            if not allowed:
                connection.close()
                continue
            worker = threading.Thread(target=self._relay_connection, args=(connection,), daemon=True)
            with self.workers_lock:
                self.workers.add(worker)
            worker.start()

    def _relay_connection(self, downstream: socket.socket) -> None:
        upstream = None
        try:
            upstream = socket.create_connection(self.target, timeout=2)
            downstream.settimeout(None)
            upstream.settimeout(None)
            with self.connections_lock:
                self.connections.update((downstream, upstream))
            with selectors.DefaultSelector() as selector:
                selector.register(downstream, selectors.EVENT_READ, upstream)
                selector.register(upstream, selectors.EVENT_READ, downstream)
                while not self.stop_event.is_set():
                    events = selector.select(0.2)
                    for key, _ in events:
                        data = key.fileobj.recv(65536)
                        if not data:
                            return
                        key.data.sendall(data)
        except OSError:
            return
        finally:
            with self.connections_lock:
                self.connections.discard(downstream)
                if upstream is not None:
                    self.connections.discard(upstream)
            downstream.close()
            if upstream is not None:
                upstream.close()
            with self.workers_lock:
                self.workers.discard(threading.current_thread())
