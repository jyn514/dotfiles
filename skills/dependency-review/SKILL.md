---
name: dependency-review
description: Review third-party dependencies and externally sourced tooling when a task proposes adding, updating, replacing, pinning, or vendoring a library, package, framework, plugin, action, CLI, toolchain, binary distribution, container image, or package manager. Do not use merely to inspect or use an unchanged existing dependency, action, tool, binary, or image.
---

# Dependency Review

Add dependencies through the owning component's existing package manager. Obtain external tools and artifacts through the repository's existing installation or image mechanism. A task that reasonably requires one authorizes adding it when that mechanism is already in place.

Do not introduce a package manager or installation mechanism solely for one dependency. Ask first when the owning component has none.

Before selecting or changing a dependency or external artifact, review its source scope, maintenance activity, release provenance, known security concerns, and compatibility in proportion to its authority and risk. Prefer primary sources; inspect the source when the dependency is small or receives significant authority.

Pin or lock the selected version according to repository conventions. Verify the installed artifact, image digest, or lockfile and exercise the behavior that required it.
