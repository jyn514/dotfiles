#!/usr/bin/env node

import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { prepareSession, publishSession } from "./importer.mjs";
import { checkCompatibility } from "./compatibility.mjs";
export * from "./importer.mjs";

const usage = `usage: pi-to-codex FILE_OR_SESSION_ID [--cwd DIRECTORY]

Import the selected Pi branch, text tool calls, and compacted context into Codex.
Prints the new thread ID and resume command; makes no hosted-provider requests.
Checks installed Pi/Codex compatibility once per build pair using a private local provider.
Requires Node, the installed Pi SDK, cp, cmp, and Codex (tested with 0.162.1 and 0.165.0).
Uses unstable Codex history injection and its internal paginated rollout format.
Accepts an exact Pi session UUID; existing paths take precedence.
`;

async function main() {
  const controller = new AbortController();
  let interrupted;
  const handlers = Object.fromEntries(["SIGINT", "SIGTERM"].map(signal => [signal, () => {
    interrupted = signal;
    controller.abort(new Error(`cancelled by ${signal}`));
  }]));
  try {
    const { values, positionals } = parseArgs({ options: { cwd: { type: "string" }, help: { type: "boolean", short: "h" } },
      allowPositionals: true });
    if (values.help) { process.stdout.write(usage); return; }
    if (positionals.length !== 1) throw new Error(usage.trim());
    for (const [signal, handler] of Object.entries(handlers)) process.on(signal, handler);
    const options = { cwd: values.cwd, signal: controller.signal };
    const prepared = await prepareSession(positionals[0], options);
    await checkCompatibility({ signal: controller.signal });
    const result = await publishSession(prepared, options);
    console.log(`Imported ${result.items} history items into Codex thread ${result.id}.`);
    console.log(`Resume with: codex resume '${result.id.replaceAll("'", "'\\''")}'`);
  } catch (error) {
    console.error(`pi-to-codex: ${error.message}`);
    process.exitCode = interrupted === "SIGINT" ? 130 : interrupted === "SIGTERM" ? 143 : 1;
  } finally {
    for (const [signal, handler] of Object.entries(handlers)) process.off(signal, handler);
  }
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
