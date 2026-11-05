/** Hold a real TUI tree-navigation boundary without model I/O or credentials. */
import { existsSync, writeFileSync } from "node:fs";
import { setTimeout } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  const marker = process.env.PI_TEST_RELOAD_BOUNDARY;
  if (!marker) throw new Error("Use the isolated restart-hook fixture");
  let supportsQueue = false;
  pi.on("session_start", (_event, ctx) => {
    if (!ctx.sessionManager.getEntries().some(entry => entry.type === "custom" && entry.customType === "reload-test-first")) {
      pi.appendEntry("reload-test-first", {});
      pi.appendEntry("reload-test-current", {});
    }
  });
  pi.on("session_before_tree", async () => {
    writeFileSync(`${marker}.started`, supportsQueue ? "queued" : "legacy");
    while (!existsSync(`${marker}.release`)) await setTimeout(10);
  });
  pi.registerCommand("hold-reload-boundary", {
    description: "Hold a tree-navigation boundary for the restart-hook test",
    handler: async (_args, ctx) => {
      // This fixture runs against independently installed Pi versions.
      supportsQueue = Reflect.has(ctx, "requestReload");
      await ctx.navigateTree(ctx.sessionManager.getBranch()[0].id);
    },
  });
}
