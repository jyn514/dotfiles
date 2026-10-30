
const Module = require("module");
const archive = process.argv[2];
const archiveArguments = JSON.parse(process.env.ARCHIVE_ARGUMENTS);
const state = { trees: [], renders: [], writes: [], spawns: [] };
const page = {
  title: 'quoted " title\nnext',
  evaluate: () => "complete",
  open: (_url, callback) => callback("success"),
  render: (path, options) => {
    state.renders.push([path, options]);
    return options.format !== process.env.FAILED_FORMAT;
  },
};
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === "system") return { args: [archive, ...archiveArguments] };
  if (request === "fs") return {
    makeTree: path => { state.trees.push(path); return true; },
    write: (path, contents, mode) => state.writes.push([path, contents, mode]),
  };
  if (request === "webpage") return { create: () => page };
  if (request === "child_process") return {
    spawn: (command, args) => {
      state.spawns.push([command, args]);
      return { on: (_event, callback) => callback(Number(process.env.WGET_STATUS)) };
    },
  };
  return originalLoad(request, parent, isMain);
};
global.setTimeout = callback => callback();
global.phantom = { exit: code => { throw { archiveExit: true, code }; } };
let status = 0;
try {
  require(archive);
} catch (error) {
  if (!error.archiveExit) throw error;
  status = error.code;
}
console.log("__RESULT__" + JSON.stringify({ status, state }));
