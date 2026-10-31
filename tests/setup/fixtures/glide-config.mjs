import { readFile } from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { runInThisContext } from "node:vm";
import { dirname, resolve } from "node:path";

export async function loadConfig(filename) {
  const registrations = [];
  const deleted = [];
  const executed = [];
  const includes = [];
  async function evaluate(path) {
    // Glide strips TypeScript and evaluates a classic script, not an ES module.
    const source = stripTypeScriptTypes(await readFile(path, "utf8"));
    runInThisContext(source, { filename: path });
  }
  const keymaps = new Map();
  const scope = prefix => ({
    set(modes, key, callback) {
      for (const mode of Array.isArray(modes) ? modes : [modes]) {
        keymaps.set(`${prefix}:${mode}:${key}`, callback);
      }
    },
    del(modes, key) {
      for (const mode of Array.isArray(modes) ? modes : [modes]) deleted.push([mode, key]);
    },
  });
  globalThis.glide = {
    g: {}, o: {}, keymaps: scope("global"), buf: { keymaps: scope("buffer") },
    autocmds: {
      create(event, pattern, callback) { registrations.push({ event, pattern, callback }); },
    },
    excmds: { async execute(command) { executed.push(command); } },
    include(name) {
      const promise = evaluate(resolve(dirname(filename), name));
      includes.push(promise);
      return promise;
    },
  };
  await evaluate(filename);
  await Promise.all(includes);
  await Promise.resolve();
  deleted.length = 0;
  return { glide: globalThis.glide, registrations, deleted, executed, keymaps };
}
