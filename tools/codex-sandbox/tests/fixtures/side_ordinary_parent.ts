// Real AgentManager producer, real native RPC consumer; no provider/model call.
// Loaded explicitly only by the source pane: /side must not replay this extension.
import { writeFileSync } from "node:fs";

export default function ordinaryParent(pi: any) {
  let manager: any;
  let live: any;
  pi.on("session_start", async (_event: unknown, ctx: any) => {
    const { AgentManager } = await import(process.env.SIDE_TEST_SUBAGENT_CORE!);
    manager = new AgentManager();
    const parentSessionId = ctx.sessionManager.getSessionId();
    await manager.spawnAgent({
      task_name: "ordinary", message: "", cwd: process.cwd(), parentSessionId,
      inheritedProvider: "side-attribution", inheritedModelId: "fixture-model-B-raw", thinking: "off",
    });
    const info = manager.getAgentInfo("ordinary", parentSessionId);
    // Test-only access to the actual manager-owned RPC pipe avoids model/network
    // input while exercising native Pi user_bash and its EOF shutdown path.
    live = manager.live.get(info.id);
    const state = await manager.sendCommand(live, { type: "get_state" });
    writeFileSync(process.env.SIDE_TEST_ORDINARY_RECEIPT!, JSON.stringify({
      parentPid: process.pid, childPid: info.childProcess.pid,
      parentModel: { provider: ctx.model.provider, modelId: ctx.model.id },
      childModel: { provider: state.model.provider, modelId: state.model.id },
    }));
  });
  pi.registerCommand("ordinary-start", { handler: async (_args: string, ctx: any) => {
    // Selecting an unchanged model emits no model_select. Switch away and back
    // through the public API so actual source A publication follows child B.
    const sourceModel = ctx.model;
    const other = ctx.modelRegistry.find("side-attribution", "fixture-model-B-raw");
    if (!await pi.setModel(other) || !await pi.setModel(sourceModel)) throw new Error("Source model selection failed");
    const quote = (text: string) => `'${text.replaceAll("'", "'\\''")}'`;
    await manager.sendCommand(live, { type: "bash", command:
      `python3 ${quote(process.env.SIDE_TEST_CONSUMER!)} consumer ORDINARY` });
    live.proc.stdin.write(JSON.stringify({
      id: "ordinary-guest-work", type: "bash",
      command: "printf started > ordinary-started; sleep 8; printf leaked > ordinary-late",
    }) + "\n");
  } });
  pi.on("session_shutdown", async () => { await manager?.shutdown(); });
}
