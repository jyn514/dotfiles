import { appendFileSync } from "node:fs";
import { join, relative } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const rel = relative(process.env.PI_TEST_OWNED_ROOT!, process.cwd());
if (rel.startsWith("..") || rel.startsWith("/")) throw new Error("Denied fixture needs owned cwd");
const record = (phase: string) => appendFileSync(join(process.cwd(), "denied-executed"), phase + "\n");
record("import");
export default function denied(pi: ExtensionAPI) {
  record("factory");
  pi.on("session_start", () => { record("hook"); });
}
