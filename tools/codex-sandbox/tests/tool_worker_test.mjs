import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { mkdtemp, rm, readFile, realpath, writeFile } from "node:fs/promises";
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
let nativeWorker;
let nativeSocket;

async function eventually(predicate) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await predicate()) return;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 20));
  }
  throw new Error("worker did not reach expected state");
}

async function connect(request, path = socketPath) {
  const socket = createConnection(path);
  await once(socket, "connect");
  socket.write(`${JSON.stringify({ model: null, ...request })}\n`);
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
      HOME: directory,
      CODEX_SANDBOX_TOOL_SOCKET: socketPath,
      CODEX_SANDBOX_PI_TOOL_MODULE: pathToFileURL(join(here, "tool-worker-fixture.mjs")).href,
      CODEX_SANDBOX_CANCEL_MARKER: marker,
    },
    stdio: ["ignore", "ignore", "inherit"],
  });
  await eventually(() => existsSync(socketPath));
  nativeSocket = join(directory, "native.sock");
  const staleFile = join(directory, "model.json");
  await writeFile(staleFile, JSON.stringify({ modelId: "stale-file-model" }));
  const packageDir = process.env.PI_PACKAGE_DIR ?? "/opt/agent-pi/src/packages/coding-agent";
  const manifest = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
  const publicEntry = manifest.exports?.["."]?.import;
  assert.equal(manifest.name, "@earendil-works/pi-coding-agent");
  assert.equal(typeof publicEntry, "string");
  nativeWorker = spawn(process.execPath, [resolve(here, "../image/tool-worker.mjs")], {
    cwd: directory,
    env: { ...process.env, HOME: directory, PI_CALL_MODEL: "stale-env-model",
      PI_MODEL_FILE: staleFile, CODEX_SANDBOX_TOOL_SOCKET: nativeSocket,
      CODEX_SANDBOX_PI_TOOL_MODULE: pathToFileURL(resolve(packageDir, publicEntry)).href },
    stdio: ["ignore", "ignore", "inherit"],
  });
  await eventually(() => existsSync(nativeSocket));
});

after(async () => {
  nativeWorker?.kill();
  if (nativeWorker) await once(nativeWorker, "exit");
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

const modelA = { provider: "provider-a", modelId: "model-a" };
const modelB = { provider: "provider-b", modelId: "model-b" };

function output(resultFrames) {
  const result = resultFrames.find(frame => frame.kind === "result");
  assert.ok(result, JSON.stringify(resultFrames));
  return result.result.content.map(block => block.text ?? "").join("");
}

// Native SDK execution: A is running while B starts under the same worker.
// A reads the environment only after B has completed and released its gate.
test("overlapping SDK bash calls keep their invocation models", async () => {
  const a = await connect({ tool: "bash", model: modelA, params: {
    command: "touch a-started; while [ ! -f release-a ]; do sleep 0.02; done; printf '%s' \"$PI_CALL_MODEL\"",
  } }, nativeSocket);
  const aFrames = frames(a);
  await eventually(() => existsSync(join(directory, "a-started")));
  const b = await connect({ tool: "bash", model: modelB, params: {
    command: "printf '%s' \"$PI_CALL_MODEL\"; touch release-a",
  } }, nativeSocket);
  assert.equal(output(await frames(b)), "model-b");
  assert.equal(output(await aFrames), "model-a");
});

test("explicit unknown overrides stale environment and shared file in both shell paths", async () => {
  for (const tool of ["bash", "user_bash"]) {
    const socket = await connect({ tool, model: null, params: {
      command: "printf '<%s>' \"$PI_CALL_MODEL\"",
    } }, nativeSocket);
    const resultFrames = await frames(socket);
    if (tool === "bash") assert.equal(output(resultFrames), "<>");
    else {
      assert.equal(resultFrames.filter(frame => frame.kind === "data")
        .map(frame => Buffer.from(frame.data, "base64").toString()).join(""), "<>");
      assert.equal(resultFrames.at(-1).result.exitCode, 0);
    }
  }
  assert.equal(JSON.parse(await readFile(join(directory, "model.json"), "utf8")).modelId, "stale-file-model");
});

test("human shell SDK operations receive the per-call model", async () => {
  const socket = await connect({ tool: "user_bash", model: modelB, params: {
    command: "printf '%s' \"$PI_CALL_MODEL\"",
  } }, nativeSocket);
  const resultFrames = await frames(socket);
  assert.equal(resultFrames.filter(frame => frame.kind === "data")
    .map(frame => Buffer.from(frame.data, "base64").toString()).join(""), "model-b");
});

test("missing, malformed model or caller environment prevents all execution", async () => {
  const invalid = [undefined, {}, [], "model-a", { provider: "p" },
    { modelId: "m" }, { provider: "p", modelId: "m", extra: "x" },
    { provider: "", modelId: "m" }, { provider: "p", modelId: "" },
    { provider: "p\n", modelId: "m" }, { provider: "p", modelId: "m\u007f" },
    { provider: "p", modelId: "m\u0085" }, { provider: 1, modelId: "m" }];
  for (const tool of ["bash", "user_bash", "read"]) {
    for (const model of invalid) {
      const socket = await connect({ tool, model, params: {
        command: "touch invalid-executed", path: "model.json",
      } }, nativeSocket);
      assert.deepEqual(await frames(socket), [{ kind: "error", message: "invalid call model" }]);
    }
  }
  const envRequest = await connect({ tool: "bash", model: modelA,
    env: { PI_CALL_MODEL: "injected" }, params: { command: "touch invalid-executed" } }, nativeSocket);
  assert.deepEqual(await frames(envRequest), [{ kind: "error", message: "invalid tool request" }]);
  assert.equal(existsSync(join(directory, "invalid-executed")), false);
});
