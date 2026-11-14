#!/usr/bin/env node
// Offline responses for the host tool's result presentation; no command is executed.
import { createInterface } from "node:readline";

let callId;
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  if (request.id === undefined) continue;
  let result;
  switch (request.method) {
    case "initialize":
      result = {};
      break;
    case "thread/start":
      result = { thread: { id: "fixture-thread" }, activePermissionProfile: { id: "fixture-sandbox" } };
      break;
    case "hooks/list":
      result = { data: [{ hooks: [], errors: [] }] };
      break;
    case "thread/inject_items":
      callId = request.params.items.at(-1).call_id;
      result = {};
      break;
    case "thread/guardianReview":
      result = { callId, assessment: null };
      break;
    case "command/exec": {
      const exitCode = Number(process.env.DOTFILES_TEST_HOST_EXIT_CODE ?? 0);
      result = { exitCode, stdout: "fixture output\n", stderr: exitCode ? "permission denied\n" : "" };
      break;
    }
    default:
      throw new Error(`Unexpected fixture request: ${request.method}`);
  }
  process.stdout.write(JSON.stringify({ id: request.id, result }) + "\n");
}
