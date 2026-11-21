# search-bsky-likes

Search posts liked by `jyn.dev`, or browse liked media by `theotherhappyplace.bsky.social`.
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

With no arguments, the command prints each matching media-post URL and opens a temporary local gallery in the browser.
The gallery contains lazy-loaded media previews and links to the posts.

To search all your liked posts instead:

```sh
search-bsky-likes education
search-bsky-likes education AI
search-bsky-likes --json credential
search-bsky-likes --profile theotherhappyplace.bsky.social --media-only
search-bsky-likes --profile @writer.example education
search-bsky-likes --help
```

Every term must occur, ignoring case, in the post text, quoted post text, link URLs, or link-card titles and descriptions.
Quote an argument containing spaces to match that phrase.
The command searches the metadata returned by Bluesky, not article bodies or surrounding replies.
Without a profile filter, it reads all pages of your likes, 100 posts per request, without separate post-hydration requests.
`--profile HANDLE|DID` selects the author of the liked post, not whose likes to search.
Handles accept an optional `@` prefix.
A profile search reads that author's feed and checks your authenticated like status, excluding their reposts of other authors.
`--media-only` keeps posts with attached images, video, or image galleries.
Article-preview thumbnails and media inside quoted posts do not count; a quote with its own attached images or video does count.
Filters combine with each other and with text terms.
Filters or `--json` without text terms list liked posts without a text restriction.
Search mode prints matching post URLs, text, and article links without opening a gallery.
`--json` prints one object per matching post with `url`, `text`, `links`, `author`, and `hasMedia`.
Each link has `url` and optional `title` and `description`; `author` contains `did` and `handle`.
Different previews of the same URL are retained when the liked and quoted posts supply different metadata.
`hasMedia` uses the same definition as `--media-only`.
Progress goes to stderr.
A failed request exits nonzero, and any results already printed are partial.

For repeated local filtering without another network scan, save the JSON lines once:

```sh
search-bsky-likes --json > likes.jsonl
jq 'select(.author.handle == "theotherhappyplace.bsky.social" and .hasMedia)' likes.jsonl
```

The first run opens Bluesky authorization in a browser.
Later runs reuse and refresh the saved OAuth session.
New authorizations request the audience-qualified `app.bsky.feed.getAuthorFeed` and `app.bsky.feed.getActorLikes` RPC permissions, with no repository-write access.
An existing author-feed-only session requires authorization again after upgrading, even for the gallery.
The requested scope is part of the loopback OAuth client ID, so the new client cannot refresh the old client's tokens.
Run the command on the host where browser authorization and the saved session are available.
`--help` works without authentication, network access, or installed npm dependencies.
