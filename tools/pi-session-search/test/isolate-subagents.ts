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

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after } from "node:test";

const sandbox = mkdtempSync(join(tmpdir(), "pi-search-subagent-isolation-"));
const original = process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT;
process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT = join(sandbox, "missing");
after(() => {
	if (original === undefined) delete process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT;
	else process.env.PI_SESSION_SEARCH_SUBAGENT_ROOT = original;
	rmSync(sandbox, { recursive: true, force: true });
});
