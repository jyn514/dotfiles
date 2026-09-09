# Sandbox instructions

- Treat this process as a disposable container, not the host, but remember that mounted writes persist. Before changing configuration or diagnosing missing state, distinguish guest state, host mounts, and external services.
- `/src` is a read-only view of the host's source directory. The current repository is overlaid writable at its host-relative path beneath `/src` when possible, and the initial working directory names that path; do not modify neighboring repositories.
- Repository metadata and sandbox policy—including `.git`, `.jj`, and `.agents/sandbox`—are protected. Use ordinary wrapped commands such as `jj`; proxy failure is fail-closed and does not authorize bypassing the mount or invoking another binary.
- A command, credential, file, or daemon missing here may exist on the host. When that distinction matters, inspect the launcher, mounts, environment, or proxy boundary.
- Most `/home/codex/.pi/agent` state is private and disposable. Sessions and package stores persist, while staged configuration is read-only; edit its tracked source and start a new sandbox session to refresh startup-loaded state.
- `/home/codex/.agents/skills` is writable and host-backed. Shared and sandbox instructions under `/home/codex/.agents` are staged read-only; edit their tracked source instead.
- Host and private-network services are blocked except through designated relays or proxies. Proxy capabilities are fixed at session startup; direct failure does not authorize another route.
- Public network acccess is allowed, but must be READ-ONLY unless explicitly authorized by a human.
  Be considerate of others and do not hammer expensive network endpoints.
- Root, `sudo`, and the exposed `docker` or `podman` command do not grant access to the outer container daemon or sibling proxy containers.
  You may use `sudo` to install user-wide tools.
