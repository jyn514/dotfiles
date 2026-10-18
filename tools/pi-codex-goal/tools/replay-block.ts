import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

import { InMemoryCredentialStore, InMemoryModelsStore, type ModelThinkingLevel } from "@earendil-works/pi-ai";
import type * as Pi from "@earendil-works/pi-coding-agent";

import { applyGuidance, compareDecisions, loadGuidance, prepareSeed, replayDecision } from "./block-decision-replay.ts";

const HELP = `Replay the decision immediately before a historical whole-goal block.

Usage: npm run replay:block -- --session FILE --before ENTRY_ID
  --baseline-src DIR --candidate-src DIR --output NEW_DIR
  --api-key-env NAME [--base-url-env NAME] [--sdk MODULE_OR_ABSOLUTE_PATH]

--session       Original Pi JSONL; only the prefix before --before enters model context.
--before        Assistant entry containing the historical update_goal(blocked) request.
--baseline-src  Trusted source directory exporting prompts.ts and tools.ts.
--candidate-src Trusted candidate source directory (usually ./src).
--output        New private evidence directory; existing directories are refused.
--api-key-env   Environment variable holding the provider API key; never archived.
--base-url-env  Optional environment variable holding the provider endpoint override.
--sdk           Pi SDK module; defaults to the installed @earendil-works/pi-coding-agent.
--max-queries   Maximum frozen get_goal calls per arm (default 3).
--timeout-ms    Timeout per model request (default 120000).
--help          Show help without calling a model.

Calls a live model and incurs provider costs. Historical workspace files are not needed.
No agent loop or external tool execution is enabled. Raw inputs/responses may be private.
Reports proposed actions, not actual goal transitions or subsequent progress.
`;

async function main(): Promise<void> {
  const { values } = parseArgs({ options: {
    session: { type: "string" }, before: { type: "string" },
    "baseline-src": { type: "string" }, "candidate-src": { type: "string" }, output: { type: "string" },
    "api-key-env": { type: "string" }, "base-url-env": { type: "string" }, sdk: { type: "string" },
    "max-queries": { type: "string", default: "3" }, "timeout-ms": { type: "string", default: "120000" },
    help: { type: "boolean", default: false },
  }, allowPositionals: false });
  if (values.help) { console.log(HELP); return; }
  for (const option of ["session", "before", "baseline-src", "candidate-src", "output", "api-key-env"] as const) {
    if (!values[option]) throw new Error(`Missing --${option}; use --help.`);
  }
  const maxQueries = Number(values["max-queries"]);
  const timeout = Number(values["timeout-ms"]);
  if (!Number.isSafeInteger(maxQueries) || maxQueries < 0) throw new Error("--max-queries must be a nonnegative integer.");
  if (!Number.isSafeInteger(timeout) || timeout <= 0) throw new Error("--timeout-ms must be a positive integer.");
  const apiKey = process.env[values["api-key-env"]!];
  if (!apiKey) throw new Error("The selected API-key environment variable is empty.");
  const baseUrl = values["base-url-env"] ? process.env[values["base-url-env"]] : undefined;
  if (values["base-url-env"] && !baseUrl) throw new Error("The selected endpoint environment variable is empty.");
  const output = resolve(values.output!);
  mkdirSync(dirname(output), { recursive: true });
  mkdirSync(output, { mode: 0o700 });
  const save = (file: string, value: unknown) => writeFileSync(resolve(output, file), JSON.stringify(value, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  const sdkName = values.sdk ?? "@earendil-works/pi-coding-agent";
  const sdk = await import(sdkName.startsWith("/") ? pathToFileURL(sdkName).href : sdkName) as typeof Pi;
  const seed = prepareSeed(resolve(values.session!), values.before!, resolve(output, "seed"), sdk);
  const baselineGuidance = await loadGuidance(resolve(values["baseline-src"]!));
  const candidateGuidance = await loadGuidance(resolve(values["candidate-src"]!));
  const baselineContext = applyGuidance(seed.context, baselineGuidance, baselineGuidance);
  const candidateContext = applyGuidance(seed.context, baselineGuidance, candidateGuidance);
  save("manifest.json", {
    cutoff: seed.cutoff, model: seed.model, thinkingLevel: seed.thinkingLevel, frozenGoal: seed.goal,
    sdk: sdkName, sdkSessionVersion: sdk.CURRENT_SESSION_VERSION,
    baselineSource: resolve(values["baseline-src"]!), candidateSource: resolve(values["candidate-src"]!),
    maxQueries, timeoutMs: timeout,
    limits: [
      "Historical context is reconstructed by the selected Pi SDK, not verified against original provider wire bytes.",
      "Selected source bundles replace standing goal guidance and goal declarations; unmatched historical rules and conversation instructions remain.",
      "No startup continuation, tool discovery, compaction, path rewriting or replay-boundary instruction is added.",
      "Only frozen get_goal queries are answered. All other calls are recorded but never executed.",
      "This is one live paired trial. Model aliases may have changed; no claim about later progress or blocking is made.",
    ],
  });
  save("baseline-guidance.json", baselineGuidance);
  save("candidate-guidance.json", candidateGuidance);
  save("baseline-input.json", baselineContext);
  save("candidate-input.json", candidateContext);
  const runtime = await sdk.ModelRuntime.create({
    allowModelNetwork: false, refreshOnCreate: false, modelsPath: null,
    credentials: new InMemoryCredentialStore(), modelsStore: new InMemoryModelsStore(),
  });
  runtime.registerProvider(seed.model.provider, { apiKey, ...(baseUrl ? { baseUrl } : {}) });
  const model = runtime.getModel(seed.model.provider, seed.model.modelId);
  if (!model) throw new Error(`Recorded model unavailable: ${seed.model.provider}/${seed.model.modelId}`);
  const thinking = seed.thinkingLevel as ModelThinkingLevel;
  if (!["off", "minimal", "low", "medium", "high", "xhigh"].includes(thinking)) {
    throw new Error(`Unsupported recorded thinking level: ${thinking}`);
  }
  const runArm = async (name: "baseline" | "candidate", context: typeof baselineContext) => {
    let request = 0;
    const sessionId = randomUUID();
    return replayDecision(context, seed.goal, async input => {
      save(`${name}-request-${++request}.json`, input);
      const response = await runtime.completeSimple(model, input, {
        ...(thinking === "off" ? {} : { reasoning: thinking }),
        sessionId, maxTokens: 8000, signal: AbortSignal.timeout(timeout),
      });
      save(`${name}-response-${request}.json`, response);
      return response;
    }, maxQueries);
  };
  console.error(`Replaying ${seed.model.provider}/${seed.model.modelId}; external tools disabled.`);
  const baseline = await runArm("baseline", baselineContext);
  save("baseline-decision.json", baseline);
  const candidate = await runArm("candidate", candidateContext);
  save("candidate-decision.json", candidate);
  const comparison = compareDecisions(baseline, candidate);
  save("comparison.json", comparison);
  console.log(`Baseline: ${baseline.kind}\nCandidate: ${candidate.kind}\nResult: ${comparison.outcome}\n${comparison.reason}\nEvidence: ${output}`);
  if (comparison.outcome === "inconclusive") process.exitCode = 2;
  else if (comparison.outcome === "block_reproduced") process.exitCode = 1;
}

main().catch(error => { console.error(`Replay failed: ${String(error)}`); process.exitCode = 2; });
