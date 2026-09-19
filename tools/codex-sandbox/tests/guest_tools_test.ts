import { test, expect } from "bun:test";
import { rewritePiResourcePaths } from "../../../config/agents/pi/pi-extensions/guest-tools-core.ts";

test("host Pi resource paths are rewritten to guest paths", () => {
  const host = "/Users/jyn/.local/share/pi/node/node_modules/@earendil-works/pi-coding-agent";
  const guest = "/opt/agent-pi/src/packages/coding-agent";
  const prompt = [
    `Main documentation: ${host}/README.md`,
    `Additional docs: ${host}/docs`,
    `Examples: ${host}/examples`,
  ].join("\n");

  const rewritten = rewritePiResourcePaths(prompt, {
    [`${host}/README.md`]: `${guest}/README.md`,
    [`${host}/docs`]: `${guest}/docs`,
    [`${host}/examples`]: `${guest}/examples`,
  });

  expect(rewritten).not.toContain(host);
  expect(rewritten).toContain(`${guest}/README.md`);
  expect(rewritten).toContain(`${guest}/docs`);
  expect(rewritten).toContain(`${guest}/examples`);
});
