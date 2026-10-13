import { pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

export async function loadConfig(filename) {
  const registrations = [];
  const deleted = [];
  const executed = [];
  const includes = [];
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
      const promise = import(pathToFileURL(resolve(dirname(filename), name)));
      includes.push(promise);
      return promise;
    },
  };
  await import(pathToFileURL(filename));
  await Promise.all(includes);
  await Promise.resolve();
  deleted.length = 0;
  return { glide: globalThis.glide, registrations, deleted, executed, keymaps };
}
