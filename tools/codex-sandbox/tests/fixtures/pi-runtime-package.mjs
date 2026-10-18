import assert from 'node:assert/strict';
import { accessSync, existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { join } from 'node:path';

const root = '/opt/agent-pi';
const pkg = `${root}/src/packages/coding-agent`;
assert(lstatSync(`${root}/standalone`).isSymbolicLink());
assert.equal(realpathSync(`${root}/standalone/pi`), `${pkg}/dist/pi`);
assert(!existsSync(`${root}/src/node_modules/typescript/package.json`));
assert(!existsSync(`${root}/src/scripts`));
for (const name of ['README.md', 'package.json', 'docs', 'examples', 'dist/modes/interactive/theme',
                    'dist/core/export-html/template.html', 'dist/assets', 'dist/photon_rs_bg.wasm']) {
    accessSync(join(pkg, name));
}
const sdk = await import(`${pkg}/dist/index.js`);
for (const name of ['createReadTool', 'createBashTool', 'createEditTool', 'createWriteTool',
                    'createGrepTool', 'createFindTool', 'createLsTool', 'loadSkills']) {
    assert.equal(typeof sdk[name], 'function', name);
}
const config = await import(`${pkg}/dist/config.js`);
const themes = config.getThemesDir();
for (const name of readdirSync(themes)) {
    if (name.endsWith('.json')) JSON.parse(readFileSync(join(themes, name), 'utf8'));
}
accessSync(join(config.getExportTemplateDir(), 'template.html'));
