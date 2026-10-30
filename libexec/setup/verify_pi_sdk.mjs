import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Use the public SDK entrypoint, as independent SDK consumers do. The bundled
// CLI can run even when the unbundled SDK resolves incompatible dependencies.
const directory = process.argv[2];
const manifest = JSON.parse(await readFile(resolve(directory, "package.json"), "utf8"));
const entry = manifest.exports?.["."]?.import;
if (manifest.name !== "@earendil-works/pi-coding-agent" || typeof entry !== "string") {
  throw new Error("installed Pi SDK has no public root import export");
}
const sdk = await import(pathToFileURL(resolve(directory, entry)).href);
if (typeof sdk.SessionManager?.open !== "function" || typeof sdk.convertToLlm !== "function") {
  throw new Error("installed Pi SDK lacks SessionManager.open or convertToLlm");
}
