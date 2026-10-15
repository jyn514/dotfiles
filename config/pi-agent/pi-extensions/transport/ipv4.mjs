// Keep transport helpers inside the extension tree copied into sandbox images.
import { realpathSync } from "node:fs";
import { createRequire } from "node:module";

// Use the installed Pi dependency, including when its CLI is a symlink.
export function createIpv4Fetch(entrypoint) {
  const require = createRequire(realpathSync(entrypoint));
  const { EnvHttpProxyAgent, fetch } = require("undici");
  const dispatcher = new EnvHttpProxyAgent({ allowH2: false, proxyTunnel: true,
    bodyTimeout: 300000, headersTimeout: 300000,
    connect: { family: 4, autoSelectFamily: false } });
  return { fetch: (input, init) => fetch(input, { ...init, dispatcher }),
    close: () => dispatcher.close() };
}
