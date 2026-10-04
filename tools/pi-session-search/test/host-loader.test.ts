/*
Copyright 2026 Adobe. All rights reserved.
This file is licensed to you under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License. You may obtain a copy
of the License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
OF ANY KIND, either express or implied. See the License for the specific language
governing permissions and limitations under the License.
*/

import { strict as assert } from "node:assert";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";

it("loads the package through Pi's real TypeScript extension loader", async () => {
	const sandbox = mkdtempSync(join(tmpdir(), "pi-session-host-loader-"));
	try {
		// Isolate discovery from the user's agent settings and project extensions.
		const packageDir = fileURLToPath(new URL("../", import.meta.url));
		const result = await discoverAndLoadExtensions([packageDir], sandbox, join(sandbox, "agent"));
		assert.deepEqual(result.errors, []);
		assert.deepEqual(result.warnings, []);
		assert.equal(result.extensions.length, 1);
		const extension = result.extensions[0];
		assert.deepEqual([...extension.tools.keys()].sort(), ["read_session", "search_sessions"]);
		assert.deepEqual([...extension.commands.keys()], ["find-sessions"]);
	} finally {
		rmSync(sandbox, { recursive: true, force: true });
	}
});
