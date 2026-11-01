import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export class CodexClient {
  constructor({ command = "codex", signal, env = process.env, cwd } = {}) {
    this.pending = new Map();
    this.nextId = 0;
    this.diagnostics = "";
    this.signal = signal;
    signal?.throwIfAborted();
    this.process = spawn(command, ["app-server", "--stdio"], { stdio: ["pipe", "pipe", "pipe"], env, cwd });
    this.exited = new Promise(resolveExit => this.process.once("close", (code, signal) => {
      this.status = { code, signal };
      this.fail(new Error(`Codex app-server exited (${code ?? signal})${this.diagnostics ? `: ${this.diagnostics.trim()}` : ""}`));
      resolveExit(this.status);
    }));
    this.process.on("error", error => this.fail(error));
    this.process.stdin.on("error", error => this.fail(error));
    this.process.stderr.setEncoding("utf8");
    this.process.stderr.on("data", chunk => { this.diagnostics = (this.diagnostics + chunk).slice(-16384); });
    this.lines = createInterface({ input: this.process.stdout });
    this.lines.on("line", line => {
      try {
        const message = JSON.parse(line);
        if (message.method !== undefined) {
          if (message.id !== undefined) this.send({ id: message.id,
            error: { code: -32601, message: "client does not implement server requests" } });
          return;
        }
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else if (Object.hasOwn(message, "result")) pending.resolve(message.result);
        else pending.reject(new Error("Codex returned a response without a result"));
      } catch (error) { this.fail(error); }
    });
    // EOF lets app-server cancel reviews and terminate command process groups.
    // Killing the server first can strand descendants; close() bounds shutdown.
    this.abort = () => { this.fail(signal.reason); this.process.stdin.end(); };
    signal?.addEventListener("abort", this.abort, { once: true });
  }

  fail(error) {
    this.failure ??= error;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(this.failure);
    }
    this.pending.clear();
  }

  send(message) { this.process.stdin.write(JSON.stringify(message) + "\n"); }

  // Most importer calls are short. Review and command execution can supply their
  // own deadline without changing the default for independently deployed callers.
  request(method, params, { timeoutMs = 30000 } = {}) {
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex did not answer ${method} within ${timeoutMs / 1000} seconds`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ id, method, params });
    });
  }

  async initialize(clientInfo = { name: "pi_to_codex", version: "1.0.0" }) {
    await this.request("initialize", { clientInfo,
      capabilities: { experimentalApi: true } });
    this.send({ method: "initialized", params: {} });
  }

  async close() {
    this.process.stdin.end();
    let timer;
    let killTimer;
    try {
      timer = setTimeout(() => {
        this.process.kill("SIGTERM");
        killTimer = setTimeout(() => this.process.kill("SIGKILL"), 1000);
      }, 1000);
      const status = await this.exited;
      if (status.code !== 0) throw new Error(`Codex app-server did not exit cleanly (${status.code ?? status.signal})`);
    } finally {
      clearTimeout(timer);
      clearTimeout(killTimer);
      this.lines.close();
      this.signal?.removeEventListener("abort", this.abort);
    }
  }
}
