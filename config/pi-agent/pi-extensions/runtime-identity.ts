import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
import { chmodSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type RuntimeModel = { provider: string; id: string };

export function publishRuntimeIdentity(model: RuntimeModel): void {
	const path = process.env.PI_MODEL_FILE;
	const sessionId = process.env.PI_MODEL_SESSION_ID;
	if (!path || !sessionId) return;

	const directory = dirname(path);
	mkdirSync(directory, { recursive: true, mode: 0o700 });
	const temporary = `${path}.${randomUUID()}.tmp`;
	writeFileSync(temporary, JSON.stringify({
		session_id: sessionId,
		provider: model.provider,
		modelId: model.id,
	}) + "\n", { mode: 0o600 });
	chmodSync(temporary, 0o600);
	renameSync(temporary, path);
}

export default function runtimeIdentity(pi: ExtensionAPI): void {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.model) publishRuntimeIdentity(ctx.model);
	});
	pi.on("model_select", (event) => publishRuntimeIdentity(event.model));
}
