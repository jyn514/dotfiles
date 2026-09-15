import asyncio
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "agent_supervisor", ROOT / "tools/codex-sandbox/image/agent_supervisor.py"
)
agent_supervisor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(agent_supervisor)


class AgentSupervisorTest(unittest.IsolatedAsyncioTestCase):
    def test_parses_only_a_fixed_host_and_port(self):
        self.assertEqual(("gateway", 2225), agent_supervisor.parse_address("gateway:2225"))
        for invalid in ("gateway", ":2225", "gateway:0", "gateway:65536"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    agent_supervisor.parse_address(invalid)

    def test_signal_exit_uses_shell_status(self):
        self.assertEqual(143, agent_supervisor.exit_status(-15))

    async def test_relays_concurrent_half_closed_connections(self):
        async def echo(reader, writer):
            data = await reader.read()
            writer.write(data.upper())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        upstream_port = upstream.sockets[0].getsockname()[1]
        relay = agent_supervisor.FixedRelay(("127.0.0.1", upstream_port))
        listener = await asyncio.start_server(relay.connect, "127.0.0.1", 0)
        relay_port = listener.sockets[0].getsockname()[1]

        async def exchange(message):
            reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
            writer.write(message)
            await writer.drain()
            writer.write_eof()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response

        try:
            self.assertEqual(
                [b"FIRST", b"SECOND"],
                await asyncio.gather(exchange(b"first"), exchange(b"second")),
            )
        finally:
            listener.close()
            upstream.close()
            await listener.wait_closed()
            await relay.stop()
            await upstream.wait_closed()

    async def test_failed_upstream_connection_closes_only_that_client(self):
        temporary = await asyncio.start_server(lambda _reader, _writer: None, "127.0.0.1", 0)
        unused_port = temporary.sockets[0].getsockname()[1]
        temporary.close()
        await temporary.wait_closed()
        relay = agent_supervisor.FixedRelay(("127.0.0.1", unused_port))
        listener = await asyncio.start_server(relay.connect, "127.0.0.1", 0)
        relay_port = listener.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
            self.assertEqual(b"", await asyncio.wait_for(reader.read(), timeout=1))
            writer.close()
            await writer.wait_closed()
        finally:
            listener.close()
            await listener.wait_closed()
            await relay.stop()


if __name__ == "__main__":
    unittest.main()
