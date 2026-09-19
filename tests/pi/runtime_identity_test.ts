import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import runtimeIdentity from "../../config/agents/pi/pi-extensions/runtime-identity";

describe("Pi runtime identity", () => {
	test("publishes the session model at startup and after a model switch", () => {
		const directory = mkdtempSync(join(tmpdir(), "pi-runtime-identity-"));
		const file = join(directory, "model.json");
		const previous = {
			file: process.env.PI_MODEL_FILE,
			session: process.env.PI_MODEL_SESSION_ID,
		};
		process.env.PI_MODEL_FILE = file;
		process.env.PI_MODEL_SESSION_ID = "session-1";
		const handlers: Record<string, (...args: any[]) => void> = {};
		try {
			runtimeIdentity({
				on(event: string, handler: (...args: any[]) => void) {
					handlers[event] = handler;
					return () => {};
				},
			} as any);

			handlers.session_start({}, { model: { provider: "openai-codex", id: "gpt-5.6-luna" } });
			expect(JSON.parse(readFileSync(file, "utf8"))).toEqual({
				session_id: "session-1",
				provider: "openai-codex",
				modelId: "gpt-5.6-luna",
			});

			handlers.model_select({ model: { provider: "openai-codex", id: "gpt-5.6-sol" } });
			expect(JSON.parse(readFileSync(file, "utf8")).modelId).toBe("gpt-5.6-sol");
		} finally {
			if (previous.file === undefined) delete process.env.PI_MODEL_FILE;
			else process.env.PI_MODEL_FILE = previous.file;
			if (previous.session === undefined) delete process.env.PI_MODEL_SESSION_ID;
			else process.env.PI_MODEL_SESSION_ID = previous.session;
			rmSync(directory, { recursive: true, force: true });
		}
	});
});
