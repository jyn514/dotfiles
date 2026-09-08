# search-bsky-likes

Find media posts by `theotherhappyplace.bsky.social` liked by `jyn.dev`.
The command uses narrowly scoped AT Protocol OAuth and stores the resulting
session under `$XDG_STATE_HOME/search-bsky-likes/` or
`~/.local/state/search-bsky-likes/`.

Install dependencies once:

```sh
cd tools/search-bsky-likes
npm install
```

Then run:

```sh
search-bsky-likes
```

The first run opens Bluesky authorization in a browser. Later runs reuse and
refresh the saved OAuth session. The tool requests only the audience-qualified
`app.bsky.feed.getAuthorFeed` RPC permission, with no repository-write access.
