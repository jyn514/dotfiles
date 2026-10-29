// Resolve Dashboard's split packages using Node's native module lookup paths.
import { createRequire } from 'node:module';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { join } from 'node:path';

if (process.argv[3] === '--extension') {
  const name = '@blackbelt-technology/pi-dashboard-extension';
  const require = createRequire(join(process.argv[2], 'package.json'));
  const manifest = require.resolve.paths(name)
    .map(directory => join(directory, name, 'package.json'))
    .find(existsSync);
  if (!manifest) throw new Error(`Cannot resolve ${name} from ${process.argv[2]}`);
  if (JSON.parse(readFileSync(manifest, 'utf8')).name !== name) {
    throw new Error(`Unexpected Dashboard package metadata: ${manifest}`);
  }
  console.log(realpathSync(join(manifest, '..')));
  process.exit(0);
}

const components = ['server', 'extension', 'shared', 'web'];
const roots = Object.fromEntries(components.map(name => [name, new Set()]));
const pending = [process.argv[2]];
const visited = new Set();
while (pending.length) {
  const root = pending.pop();
  if (visited.has(root)) continue;
  visited.add(root);
  const require = createRequire(join(root, 'package.json'));
  for (const component of components) {
    const name = `@blackbelt-technology/pi-dashboard-${component}`;
    const manifest = require.resolve.paths(name)
      .map(directory => join(directory, name, 'package.json'))
      .find(existsSync);
    if (!manifest) continue;
    if (JSON.parse(readFileSync(manifest, 'utf8')).name !== name) {
      throw new Error(`Unexpected Dashboard package metadata: ${manifest}`);
    }
    const resolved = realpathSync(join(manifest, '..'));
    roots[component].add(resolved);
    pending.push(resolved);
  }
}
if (process.argv[3] === '--versions') {
  const packages = new Map();
  const peers = ['@earendil-works/pi-coding-agent', '@earendil-works/pi-ai', '@earendil-works/pi-tui'];
  for (const root of visited) {
    const require = createRequire(join(root, 'package.json'));
    packages.set(realpathSync(join(root, 'package.json')), null);
    for (const name of peers) {
      const manifest = require.resolve.paths(name)
        .map(directory => join(directory, name, 'package.json'))
        .find(existsSync);
      if (manifest) packages.set(realpathSync(manifest), null);
    }
  }
  console.log(JSON.stringify([...packages.keys()].sort().map(manifest => {
    const { name, version } = JSON.parse(readFileSync(manifest, 'utf8'));
    return { name, version, path: realpathSync(join(manifest, '..')) };
  })));
} else {
  console.log(JSON.stringify(Object.fromEntries(
    components.map(name => [name, [...roots[name]].sort()]),
  )));
}
