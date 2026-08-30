import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  const baseUrl = process.env.CODEX_SIDECAR_URL;
  const apiKey = process.env.CODEX_SIDECAR_KEY;
  if (!baseUrl || !apiKey) return;
  pi.registerProvider("openai-codex", { baseUrl, apiKey });
}
