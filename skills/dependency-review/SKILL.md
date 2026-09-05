---
name: dependency-review
description: Review and add third-party dependencies when a task proposes a new library, package, module, framework, or package manager. Do not use for merely using existing dependencies.
---

# Dependency Review

Add dependencies through the owning component's existing package manager. A task that reasonably requires a dependency authorizes adding it when that package manager is already in place.

Do not introduce a package manager solely for one dependency. Ask first when the owning component has none.

Before adding a dependency, review its source scope, maintenance activity, release provenance, known security concerns, and compatibility in proportion to its authority and risk. Prefer primary sources; inspect the source when the dependency is small or receives significant authority.

Pin or lock the selected version according to repository conventions. Verify the installed artifact or lockfile and exercise the behavior that required the dependency.
