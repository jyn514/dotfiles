#!/usr/bin/env python3
"""Run Pi with an optional fixed-target agent-room loopback relay."""

from __future__ import annotations

import asyncio
import os
import signal
import sys


PI = "/opt/agent-pi/bin/pi"
READINESS_TIMEOUT = float(os.environ.get("CODEX_SANDBOX_GATEWAY_RETRY_SECONDS", "15"))


def exit_status(status: int) -> int:
    return 128 - status if status < 0 else status


def parse_address(value: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        raise ValueError("agent-room gateway address must be host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ValueError("agent-room gateway port is out of range")
    return host, port


async def copy_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()
        await writer.drain()


class FixedRelay:
    def __init__(self, target: tuple[str, int]) -> None:
        self.target = target
        self.connections: set[asyncio.Task[None]] = set()

    async def connect(self, downstream_reader: asyncio.StreamReader,
                      downstream_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.connections.add(task)
        upstream_writer = None
        pumps: list[asyncio.Task[None]] = []
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*self.target)
            pumps = [
                asyncio.create_task(copy_stream(downstream_reader, upstream_writer)),
                asyncio.create_task(copy_stream(upstream_reader, downstream_writer)),
            ]
            await asyncio.gather(*pumps)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            for pump in pumps:
                pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            downstream_writer.close()
            if upstream_writer is not None:
                upstream_writer.close()
            closing = [downstream_writer.wait_closed()]
            if upstream_writer is not None:
                closing.append(upstream_writer.wait_closed())
            await asyncio.gather(*closing, return_exceptions=True)
            self.connections.discard(task)

    async def stop(self) -> None:
        connections = list(self.connections)
        for task in connections:
            task.cancel()
        if connections:
            await asyncio.gather(*connections, return_exceptions=True)


async def verify_target(target: tuple[str, int]) -> None:
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(*target), timeout=READINESS_TIMEOUT,
    )
    writer.close()
    await writer.wait_closed()


async def supervise(arguments: list[str], address: str) -> int:
    target = parse_address(address)
    relay = FixedRelay(target)
    server = await asyncio.start_server(relay.connect, "127.0.0.1", 3000)
    try:
        await verify_target(target)
        pi = await asyncio.create_subprocess_exec(PI, "--offline", "--approve", *arguments)
        loop = asyncio.get_running_loop()
        installed = []
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, pi.send_signal, signum)
            installed.append(signum)
        try:
            return exit_status(await pi.wait())
        finally:
            for signum in installed:
                loop.remove_signal_handler(signum)
    finally:
        server.close()
        await server.wait_closed()
        await relay.stop()


def main(arguments: list[str]) -> int:
    address = os.environ.get("CODEX_SANDBOX_AGENT_ROOM_ADDRESS")
    if not address:
        os.execv(PI, [PI, "--offline", "--approve", *arguments])
    try:
        return asyncio.run(supervise(arguments, address))
    except (OSError, ValueError, asyncio.TimeoutError) as error:
        print(f"agent-room relay: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
