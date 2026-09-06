const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 19)) {
    throw new Error(`Pi requires Node >=22.19.0 on Alpine; found ${process.version}`);
}
