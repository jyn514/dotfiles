import { writeFileSync } from "node:fs";

writeFileSync(process.env.CODEX_SANDBOX_WARM_MARKER, "module-loaded");
