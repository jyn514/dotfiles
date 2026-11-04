import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { existsSync, writeFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import type { ChildEndpoint, ParentEndpoint } from "../extension-channel.ts";

/** A generic extension consumer. No question protocol, transport implementation, or model stub. */
export default function (pi: ExtensionAPI) {
  let endpoint: ChildEndpoint | ParentEndpoint | undefined;
  const accept = (value: any) => {
    const candidate = value?.endpoint ?? value;
    if (candidate?.version !== 1 || !["child", "parent"].includes(candidate.role) || endpoint === candidate) return;
    endpoint = candidate;
    candidate.register("fixture:echo", (payload: any) => payload);
    candidate.register("fixture:throw", () => { throw new Error("fixture handler failure"); });
    if (candidate.role === "child") {
      candidate.register("fixture:input", (payload: string) => { pi.sendUserMessage(payload); return { admitted: true }; });
      candidate.register("fixture:nested", (payload: any) => candidate.request("fixture:parent", payload));
      candidate.register("fixture:deferred-input", async ({ entered, release, message }: any) => {
        writeFileSync(entered, "handler entered");
        while (!existsSync(release)) await delay(5);
        pi.sendUserMessage(message);
        return { admitted: true };
      });
      candidate.register("fixture:pending", () => new Promise(() => {}));
      candidate.register("fixture:exit", () => { process.exit(0); });
    } else {
      candidate.register("fixture:parent", (payload: any, origin: any) => ({ payload, origin }));
    }
  };
  pi.events.on("subagents:extension-channel:v1", (value: any) => { if(value?.endpoint) accept(value); });
  pi.events.emit("subagents:extension-channel:v1", { version: 1, provide: accept });
  pi.registerTool({
    name: "fixture_request", label: "Generic channel request", description: "Exercise a generic channel through the native tool loop.",
    parameters: Type.Object({ channel: Type.String(), payload: Type.Any() }),
    async execute(_id, { channel, payload }) {
      if (endpoint?.role !== "child") throw new Error("Expected a child endpoint");
      const result = await endpoint.request(channel, payload);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });
  pi.registerCommand("fixture-parent-request", {
    description: "Invoke parent endpoint without involving the parent model",
    handler: async args => {
      if (endpoint?.role !== "parent") throw new Error("Expected parent endpoint");
      const { workerId, channel, payload } = JSON.parse(args);
      try {
        const result = await endpoint.request(workerId, channel, payload);
        pi.appendEntry("fixture-parent-result", { ok: true, result });
      } catch (error: any) { pi.appendEntry("fixture-parent-result", { ok: false, code: error.code, message: error.message }); }
    },
  });
}
