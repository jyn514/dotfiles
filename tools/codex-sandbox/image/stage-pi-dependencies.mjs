import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

// npm's lockfile records workspace paths, including nested example workspaces.
// Copy only install inputs so source-only Pi updates reuse the npm ci layer.
const [source, destination] = process.argv.slice(2).map(path => resolve(path));
const lock = JSON.parse(readFileSync(join(source, "package-lock.json"), "utf8"));
const copy = path => {
    const target = join(destination, path);
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(join(source, path), target);
};

copy("package-lock.json");
if (existsSync(join(source, ".npmrc"))) copy(".npmrc");
for (const path of Object.keys(lock.packages)) {
    if (!path.split("/").includes("node_modules")) copy(join(path, "package.json"));
}
