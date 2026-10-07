= Bake resolver: cache ownership

This is the bundled resolver's cache contract under
#link("launcher-interface.typ")[the launcher interface]; it does not constrain
project resolvers.

Native, quiet `bake --print` resolves build settings; evaluate with controlled
environment inputs rather than caching arbitrary Bake expressions by file bytes.

Capture and hash the Dockerfile and selected inputs of every local filesystem
context, including named contexts. Main contexts use `.dockerignore`, with a
Dockerfile-specific ignore file taking precedence. Filter before copying and
hashing, pruning excluded directories unless exceptions or required build controls
need their contents. Retain the Dockerfile and selected ignore file in the snapshot;
parse and capture the same ignore bytes. Named local contexts remain unfiltered.
Require each
Dockerfile to be inside its captured context; reject configurations that expose
uncaptured local files to the builder. Named image dependencies use immutable
image identities instead of filesystem snapshots.

Hash paths, entry types, contents, relevant permissions, and symlink destinations.
Reject escaping links and special files among selected inputs; ignore files must
be regular files rather than symlinks. Use docker-py 7.2.0's internal `Pattern`
normalization and `fnmatchcase` implementation through the local adapter, with
corrections for case sensitivity, wildcard exception traversal, and matching all
ancestors. The pinned dependency and regression tests protect this internal SDK
boundary; full BuildKit pattern equivalence is not guaranteed.
These restrictions belong to the bundled resolver, not
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
