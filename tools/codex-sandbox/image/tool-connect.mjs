import { connect } from "node:net";

const socket = connect(process.env.CODEX_SANDBOX_TOOL_SOCKET ?? "/tmp/codex-tool-worker.sock");
socket.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
process.stdin.pipe(socket);
socket.pipe(process.stdout);
