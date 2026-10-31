import { execFileSync } from "node:child_process";
import {
    copyFileSync, cpSync, existsSync, lstatSync, mkdirSync, readdirSync,
    readFileSync, readlinkSync, realpathSync, symlinkSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { parseArgs } from "node:util";

const { values, positionals } = parseArgs({
    options: { "omit-standalone": { type: "boolean" }, extensions: { type: "string" } },
    allowPositionals: true,
});
if (positionals.length !== 2) throw new Error("Pass the built Pi tree and runtime destination");
const [built, output] = positionals.map(path => resolve(path));
const source = join(built, "src");
const destination = join(output, "src");
const npm = args => execFileSync("npm", args, {
    cwd: source, encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
    stdio: ["ignore", "pipe", "inherit"],
});
const copy = (from, to) => {
    mkdirSync(dirname(to), { recursive: true });
    cpSync(from, to, { recursive: true, verbatimSymlinks: true });
};

// npm owns dependency selection, including transitive and nested dependencies.
// Keep their installed paths so workspace links and Node resolution still work.
const listing = npm([
    "ls", "--omit=dev", "--all", "--parseable", "--workspace=packages/coding-agent",
]);
const packages = listing.trim().split("\n").filter(path => path && path !== source);
if (!packages.length) throw new Error("npm returned no runtime packages for coding-agent");
const workspaces = new Set();
for (const path of new Set(packages)) {
    const target = join(destination, relative(source, path));
    if (lstatSync(path).isSymbolicLink()) {
        const workspace = realpathSync(path);
        workspaces.add(workspace);
        mkdirSync(dirname(target), { recursive: true });
        symlinkSync(readlinkSync(path), target);
    } else {
        copy(path, target);
    }
}

// Use npm's published file list rather than duplicating Pi's asset rules.
for (const workspace of workspaces) {
    const [packed] = JSON.parse(npm([
        "pack", workspace, "--dry-run", "--json", "--ignore-scripts", "--workspaces=false",
    ]));
    for (const { path } of packed.files) {
        if (values["omit-standalone"] && join(workspace, path) === join(source, "packages/coding-agent/dist/pi")) {
            continue;
        }
        copy(join(workspace, path), join(destination, relative(source, workspace), path));
    }
    // Retain the matching sources for inspection without bringing build tools or tests.
    const workspaceSource = join(workspace, "src");
    if (existsSync(workspaceSource)) {
        copy(workspaceSource, join(destination, relative(source, workspace), "src"));
    }
}

// npm's .bin links are not packages. Retain only links whose runtime target survived.
for (const directory of [source, ...workspaces]) {
    const bin = join(directory, "node_modules/.bin");
    if (!existsSync(bin)) continue;
    for (const name of readdirSync(bin)) {
        const path = join(bin, name);
        const target = join(destination, relative(source, path));
        const link = readlinkSync(path);
        if (existsSync(resolve(dirname(target), link))) copy(path, target);
    }
}

// Extension dependencies resolve beside their own package, preserving Pi's lockfile graph.
// The extension tree remains at this path in the final image.
if (values.extensions) {
    const extensions = resolve(values.extensions);
    const manifest = JSON.parse(readFileSync(join(extensions, "package.json"), "utf8"));
    for (const name of Object.keys(manifest.dependencies ?? {})) {
        const target = join(destination, "node_modules", name);
        mkdirSync(dirname(target), { recursive: true });
        symlinkSync(join(extensions, "node_modules", name), target);
    }
}

copyFileSync(join(built, "REVISION"), join(output, "REVISION"));
copyFileSync(join(source, "package.json"), join(destination, "package.json"));
// copy-binary-assets already stages the binary's assets beside dist/pi.
// Share that tree with the SDK instead of copying all of dist a second time.
symlinkSync("src/packages/coding-agent/dist", join(output, "standalone"));
