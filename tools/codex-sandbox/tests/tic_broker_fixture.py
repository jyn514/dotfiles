"""Disposable protocol peer for adapter tests; never used by installed launchers."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import time


def main(mode="ready"):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--lifetime-fd", type=int)
    args = parser.parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    # Record inherited descriptor flags/environment only in this owned fixture.
    config_path.with_name("evidence.json").write_text(json.dumps({
        "mode": config_path.stat().st_mode & 0o777,
        "environment": dict(os.environ),
    }))
    if mode == "exit":
        return
    if mode == "oversize":
        print("x" * 4097, flush=True)
    elif mode == "malformed":
        print('{"version":1,"version":1}', flush=True)
    elif mode == "timeout":
        pass
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        if mode not in ("oversize", "malformed", "timeout"):
            print(json.dumps({"version": 1, "address": "127.0.0.1:" + str(listener.getsockname()[1]),
                              "native_revision": (Path(__file__).resolve().parents[2] / "tic-proxy/native-revision").read_text().strip(),
                              "policy_version": 1}), flush=True)
        if mode == "ignore-termination":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(10)
        with selectors.DefaultSelector() as selector:
            selector.register(args.lifetime_fd, selectors.EVENT_READ)
            selector.register(listener, selectors.EVENT_READ)
            while True:
                for key, _ in selector.select():
                    if key.fileobj == args.lifetime_fd:
                        if not os.read(args.lifetime_fd, 1):
                            return
                    else:
                        with listener.accept()[0] as connection:
                            connection.settimeout(2)
                            data = bytearray()
                            while True:
                                chunk = connection.recv(65536)
                                if not chunk:
                                    break
                                data.extend(chunk)
                            if not data:  # FixedTcpBridge's reachability probe.
                                continue
                            size = struct.unpack("!I", data[:4])[0]
                            request = json.loads(data[4:])
                            assert size == len(data) - 4
                            assert request["token"] == config["token"]
                            response = json.dumps({"version": 1, "exit": 0,
                                                   "stdout": "fixture response", "stderr": ""}).encode()
                            connection.sendall(struct.pack("!I", len(response)) + response)
