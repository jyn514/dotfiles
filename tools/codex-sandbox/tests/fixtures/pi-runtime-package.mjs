import assert from 'node:assert/strict';
import { accessSync, existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const root = '/opt/agent-pi';
const pkg = `${root}/src/packages/coding-agent`;
assert(lstatSync(`${root}/standalone`).isSymbolicLink());
if (existsSync('/etc/alpine-release')) {
    assert(!existsSync(`${root}/standalone/pi`));
} else {
    assert.equal(realpathSync(`${root}/standalone/pi`), `${pkg}/dist/pi`);
}
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

// Resolve extension entrypoints as the SDK does, through their isolated package tree.
const sdkRequire = createRequire(`${pkg}/package.json`);
const extensionRoot = '/opt/pi-npm';
const extensions = JSON.parse(readFileSync(`${extensionRoot}/package.json`, 'utf8'));
for (const name of Object.keys(extensions.dependencies)) {
    const entry = sdkRequire.resolve(name);
    assert(realpathSync(entry).startsWith(`${extensionRoot}/node_modules/`), entry);
}
