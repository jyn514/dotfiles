#set document(title: "Bake resolver: cache ownership")
#set page(paper: "a4", margin: 22mm)
#set text(size: 11pt)

= Bake resolver: cache ownership

Selected cache contract for the bundled resolver in
#link("launcher-interface.typ")[the launcher interface]. These choices do not
constrain project resolvers.

Native, quiet `bake --print` resolves build settings; evaluate with controlled
environment inputs rather than caching arbitrary Bake expressions by file bytes.

Each context is a complete, small input directory. Capture and hash the Dockerfile
and every local filesystem context, including named contexts. Require each
Dockerfile to be inside its captured context; reject configurations that expose
uncaptured local files to the builder. Named image dependencies use immutable
image identities instead of filesystem snapshots.

Hash paths, entry types, contents, relevant permissions, and symlink destinations.
Initially reject escaping links, special files, and `.dockerignore`; keep developer artifacts
outside these contexts. These restrictions belong to the bundled resolver, not
the common interface.

Cache identity includes effective build settings, context contents, platform,
actual dependency image identities, and the resolver's cache-contract version.
An available local image matching that identity skips BuildKit; a missing or
pruned image requires a build even when inputs are unchanged. On a miss, capture
private snapshots of all local inputs, hash the captured representation, and
repeat lookup before building exclusively from those snapshots. Bytes built
must match bytes hashed, even if the checkout changes.
The resolver evaluates all requested targets together and shares dependency
results within that invocation. It coordinates concurrent
misses and publishes cache results only after successful builds and verification.
Locks and atomic result records live in the owner-only
`/tmp/codex-sandbox-images-<uid>` directory. Acquire target locks in sorted cache-key
order, repeat image lookup while holding them, and replace a result record only
after verifying the built image. A crash may leave an unused temporary file or
lock file; neither is a cache hit, and the next invocation repeats engine lookup.
Ordinary acquisition follows the launcher's resolution-versus-refresh policy.
Its refresh command resolves updated upstream image identities and rebuilds
affected dependents while preserving valid build caches. An explicit clean
rebuild bypasses those caches; neither operation may report failure as successful
reuse. Cached steps that fetch external data require a clean rebuild to refetch
that data unless the resolver already models it as an input.

Measure quiet Bake evaluation and context hashing on complete warm launches
before adding metadata caches or file watchers.

Acceptance tests cover added, removed, renamed, and modified context entries;
permissions and symlink changes; named contexts and dependency image changes;
checkout mutation between lookup and build; concurrent misses; pruned images;
and failed or cancelled builds and refreshes. No failure may publish a reusable
result, and every successful build must consume the captured input bytes.
