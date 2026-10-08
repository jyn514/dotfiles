// Discovered from the test's owned HOME in both native Pi panes.
// Public provider registration supplies selectable models, never inference.
import { writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export default function attributionProvider(pi: ExtensionAPI) {
  const runtime = process.env.SIDE_PI_RUNTIME!;
  pi.on("input", (event) => {
    if (event.text !== "--split-prompt @file 'quoted'") return { action: "continue" };
    writeFileSync(join(runtime, "split-prompt.json"), JSON.stringify({
      text: event.text, source: event.source, pane: process.env.TMUX_PANE,
    }));
    return { action: "handled" };
  });
  pi.registerProvider("side-attribution", {
    name: "Offline integration attribution",
    baseUrl: "http://127.0.0.1:9/no-inference",
    apiKey: "owned-test-key-not-a-credential",
    api: "openai-completions",
    models: ["fixture-model-A-raw", "fixture-model-B-raw"].map(id => ({
      id, name: id, reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 8192, maxTokens: 1024,
    })),
    streamSimple() {
      writeFileSync(join(runtime, "inference-attempted"), "unexpected provider invocation\n");
      throw new Error("Attribution fixture prohibits inference and network requests");
    },
  });
  const record = (ctx: ExtensionContext, event: string) => {
    if (!ctx.model) return;
    writeFileSync(join(runtime, `ctx-model-${process.env.TMUX_PANE ?? "sdk"}.json`),
      JSON.stringify({ provider: ctx.model.provider, modelId: ctx.model.id, event, nonce: randomUUID() }));
  };
  pi.on("session_start", (_event, ctx) => record(ctx, "session_start"));
  pi.on("model_select", (_event, ctx) => record(ctx, "model_select"));
}
