# Sandbox instructions

- Treat this process as a disposable container, not the host. Before changing configuration or diagnosing missing state, distinguish guest paths, host mounts, and external services.
- `/src/work` is the writable working tree. Repository metadata and sandbox policy—including `.git`, `.jj`, and `.agents/sandbox`—are protected; use the provided commands and proxies rather than bypassing their mounts.
- A command, credential, file, or daemon missing here may exist on the host. When that distinction matters, inspect the launcher, mounts, environment, or proxy boundary.
- Files under `/home/codex/.pi/agent` and `/home/codex/.agents` may come from host configuration. Edit their tracked source, not the mounted copy; start a new sandbox session to refresh startup-loaded state.
- Network and privileged operations may be unavailable or delegated to narrow proxies. Direct failure does not authorize weakening the boundary or inventing another route.
