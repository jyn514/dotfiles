import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { mkdtemp, rm, readFile, realpath } from "node:fs/promises";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { after, before, test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
let directory;
let socketPath;
let marker;
let worker;

async function eventually(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await predicate()) return;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 20));
  }
  throw new Error("worker did not reach expected state");
}

async function connect(request) {
  const socket = createConnection(socketPath);
  await once(socket, "connect");
  socket.write(`${JSON.stringify(request)}\n`);
  return socket;
}

async function frames(socket) {
  let text = "";
  const results = [];
  for await (const chunk of socket) {
    text += chunk.toString();
    let newline;
    while ((newline = text.indexOf("\n")) >= 0) {
      results.push(JSON.parse(text.slice(0, newline)));
      text = text.slice(newline + 1);
    }
  }
  assert.equal(text, "");
  return results;
}

before(async () => {
  directory = await mkdtemp(join(await realpath(tmpdir()), "codex-tool-worker-"));
  socketPath = join(directory, "worker.sock");
  marker = join(directory, "cancelled");
  worker = spawn(process.execPath, [resolve(here, "../image/tool-worker.mjs")], {
    cwd: directory,
    env: {
      ...process.env,
      CODEX_SANDBOX_TOOL_SOCKET: socketPath,
      CODEX_SANDBOX_PI_TOOL_MODULE: pathToFileURL(join(here, "tool-worker-fixture.mjs")).href,
      CODEX_SANDBOX_CANCEL_MARKER: marker,
    },
    stdio: ["ignore", "ignore", "inherit"],
  });
  await eventually(() => existsSync(socketPath));
});

after(async () => {
  worker?.kill();
  if (worker) await once(worker, "exit");
  if (directory) await rm(directory, { recursive: true, force: true });
});

test("a guest read returns its result", async () => {
  const socket = await connect({ tool: "read", params: { path: "file.txt" } });
  assert.deepEqual(await frames(socket), [
    { kind: "result", result: { content: [{ type: "text", text: "guest:file.txt" }] } },
  ]);
});

test("unknown tools do not execute", async () => {
  const socket = await connect({ tool: "host_exec", params: {} });
  assert.deepEqual(await frames(socket), [{ kind: "error", message: "unknown tool" }]);
  const inheritedName = await connect({ tool: "constructor", params: {} });
  assert.deepEqual(await frames(inheritedName), [{ kind: "error", message: "unknown tool" }]);
});

test("a human shell command streams guest output and exit status", async () => {
  const socket = await connect({ tool: "user_bash", params: { command: "ignored" } });
  assert.deepEqual(await frames(socket), [
    { kind: "data", data: Buffer.from("guest shell output").toString("base64") },
    { kind: "result", result: { exitCode: 3 } },
  ]);
});

test("losing the caller cancels guest work", async () => {
  const socket = await connect({ tool: "bash", params: { command: "sleep" } });
  await new Promise((resolveFrame, reject) => {
    socket.once("data", (data) => {
      try {
        assert.equal(JSON.parse(data.toString().trim()).kind, "update");
        resolveFrame();
      } catch (error) {
        reject(error);
      }
    });
  });
  socket.destroy();
  await eventually(() => existsSync(marker));
  assert.equal(await readFile(marker, "utf8"), "cancelled");
});
