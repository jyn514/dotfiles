import assert from "node:assert/strict";
import { test } from "node:test";
import { searchLikes, formatResult } from "../src/search.ts";
import { canRestoreSession } from "../src/search-bsky-likes.ts";

function post(text, embed, facets) {
  return {
    uri: "at://did:plc:writer/app.bsky.feed.post/example",
    cid: "fixture-cid",
    author: { did: "did:plc:writer", handle: "writer.example" },
    record: { $type: "app.bsky.feed.post", text, facets, createdAt: "2026-10-01T00:00:00Z" },
    embed,
    indexedAt: "2026-10-01T00:00:00Z",
  };
}

function external(title, description = "") {
  return {
    $type: "app.bsky.embed.external#view",
    external: { uri: "https://example.org/article", title, description },
  };
}

async function collect(posts, terms, filters = {}) {
  const agent = { getActorLikes: async () => ({ data: { feed: posts.map(post => ({ post })) } }) };
  return Array.fromAsync(searchLikes(agent, "me.example", terms, () => {}, filters));
}

const matchingCases = [
  ["plain text without media or viewer metadata", post("Education serves too many masters"), ["education"], true],
  ["case-insensitive substrings", post("Credential factories"), ["CREDENTIAL"], true],
  ["all terms must occur", post("Education and credentials"), ["education", "AI"], false],
  ["literal phrase", post("higher education and AI"), ["higher education"], true],
  ["phrase order matters", post("education is higher priority"), ["higher education"], false],
  ["punctuation is literal, not regex", post("Education and AI"), ["edu.*"], false],
  ["link title", post("Worth a read", external("Education's competing purposes")), ["education"], true],
  ["link description combines with post text", post("AI", external("A post", "Credential factories")), ["AI", "credential"], true],
  ["link URL", post("Interesting", external("Title")), ["example.org/article"], true],
  ["no accidental match in thumbnail URL", post("Unrelated", {
    $type: "app.bsky.embed.external#view",
    external: { uri: "https://example.org/other", title: "Unrelated", description: "", thumb: "https://example.org/education.jpg" },
  }), ["education"], false],
  ["facet URL when no link card exists", post("Read this", undefined, [{
    index: { byteStart: 0, byteEnd: 4 },
    features: [{ $type: "app.bsky.richtext.facet#link", uri: "https://example.org/education" }],
  }]), ["education"], true],
  ["wrapped link card", post("AI", {
    $type: "app.bsky.embed.recordWithMedia#view",
    media: external("Education"),
    record: { $type: "app.bsky.embed.record#view", record: { $type: "app.bsky.embed.record#viewBlocked" } },
  }), ["education", "ai"], true],
  ["quoted post and its link card", post("This!", {
    $type: "app.bsky.embed.record#view",
    record: {
      $type: "app.bsky.embed.record#viewRecord",
      value: { $type: "app.bsky.feed.post", text: "Education", createdAt: "2026-10-01T00:00:00Z" },
      embeds: [external("What AI broke")],
    },
  }), ["education", "ai"], true],
  ["unavailable quote does not stop search", post("Education", {
    $type: "app.bsky.embed.record#view",
    record: { $type: "app.bsky.embed.record#viewNotFound" },
  }), ["education"], true],
];

for (const [name, input, terms, expected] of matchingCases) {
  test(name, async () => {
    const results = await collect([input], terms);
    assert.equal(results.length, expected ? 1 : 0);
    if (expected) {
      assert.equal(results[0].url, "https://bsky.app/profile/did:plc:writer/post/example");
      assert.deepEqual(results[0].author, { did: "did:plc:writer", handle: "writer.example" });
    }
  });
}

test("article metadata replaces the duplicate facet link without fetching the article", async () => {
  const facets = [{ index: { byteStart: 0, byteEnd: 4 }, features: [
    { $type: "app.bsky.richtext.facet#link", uri: "https://example.org/article" },
  ] }];
  const [result] = await collect([post("Read this", external("Education", "Many jobs"), facets)], ["education"]);
  assert.deepEqual(result.links, [{ url: "https://example.org/article", title: "Education", description: "Many jobs" }]);
  assert.equal(formatResult(result), [
    "https://bsky.app/profile/did:plc:writer/post/example",
    "Read this", "Education", "https://example.org/article", "Many jobs",
  ].join("\n"));
  assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
});

for (const terms of [["credential"], ["learning"], ["credential", "learning"]]) {
  test(`same-URL cards retain both the liked and quoted metadata: ${terms.join(" + ")}`, async () => {
    const input = post("Two perspectives", {
      $type: "app.bsky.embed.recordWithMedia#view",
      media: external("Credential factories", "Institutional incentives"),
      record: {
        $type: "app.bsky.embed.record#view",
        record: {
          $type: "app.bsky.embed.record#viewRecord",
          value: { $type: "app.bsky.feed.post", text: "A different preview", createdAt: "2026-10-01T00:00:00Z" },
          embeds: [external("Learning", "Student ambitions")],
        },
      },
    });
    const results = await collect([input], terms);
    assert.equal(results.length, 1);
    assert.deepEqual(results[0].links.map(link => link.title).sort(), ["Credential factories", "Learning"]);
    assert.equal(new Set(results[0].links.map(link => link.url)).size, 1);
  });
}

test("pagination uses 100-item requests and searches later pages, including after an empty page", async () => {
  const calls = [];
  const progress = [];
  const pages = [
    { feed: [{ post: post("Unrelated") }], cursor: "second" },
    { feed: [], cursor: "third" },
    { feed: [{ post: post("Education", external("AI")) }] },
  ];
  const agent = { getActorLikes: async args => {
    calls.push(args);
    return { data: pages.shift() };
  } };
  const results = await Array.fromAsync(searchLikes(agent, "different.example", ["education", "ai"],
    (...counts) => progress.push(counts)));
  assert.equal(results.length, 1);
  assert.deepEqual(calls, [
    { actor: "different.example", limit: 100, cursor: undefined },
    { actor: "different.example", limit: 100, cursor: "second" },
    { actor: "different.example", limit: 100, cursor: "third" },
  ]);
  assert.deepEqual(progress, [[1, 0], [1, 0], [2, 1]]);
});

test("a later page error propagates after already streamed results", async () => {
  let calls = 0;
  const agent = { getActorLikes: async () => {
    if (calls++ > 0) throw new Error("Rate limit");
    return { data: { feed: [{ post: post("Education") }], cursor: "next" } };
  } };
  const matches = searchLikes(agent, "me.example", ["education"], () => {});
  assert.equal((await matches.next()).value.text, "Education");
  await assert.rejects(matches.next(), /Rate limit/);
});

test("unknown records are skipped, and empty feeds complete without matches", async () => {
  assert.deepEqual(await collect([{ ...post("education"), record: { $type: "other.record", text: "education" } }], ["education"]), []);
  assert.deepEqual(await collect([], ["education"]), []);
});

const imageEmbed = {
  $type: "app.bsky.embed.images#view",
  images: [{ thumb: "https://example.org/thumb", fullsize: "https://example.org/full", alt: "Art" }],
};
const mediaCases = [
  ["plain text", undefined, false],
  ["attached image", imageEmbed, true],
  ["empty image list", { $type: "app.bsky.embed.images#view", images: [] }, false],
  ["attached video", { $type: "app.bsky.embed.video#view", cid: "fixture", playlist: "https://example.org/video.m3u8" }, true],
  ["image gallery", { $type: "app.bsky.embed.gallery#view", items: [
    { $type: "app.bsky.embed.gallery#viewImage", thumbnail: "https://example.org/thumb", fullsize: "https://example.org/full", alt: "Art", aspectRatio: { width: 1, height: 1 } },
  ] }, true],
  ["empty gallery", { $type: "app.bsky.embed.gallery#view", items: [] }, false],
  ["link thumbnail", { ...external("Art"), external: { ...external("Art").external, thumb: "https://example.org/thumb" } }, false],
  ["quoted image without own media", {
    $type: "app.bsky.embed.record#view",
    record: {
      $type: "app.bsky.embed.record#viewRecord",
      value: { $type: "app.bsky.feed.post", text: "Art", createdAt: "2026-10-01T00:00:00Z" },
      embeds: [imageEmbed],
    },
  }, false],
  ["own image alongside quote", {
    $type: "app.bsky.embed.recordWithMedia#view",
    media: imageEmbed,
    record: { $type: "app.bsky.embed.record#view", record: { $type: "app.bsky.embed.record#viewBlocked" } },
  }, true],
  ["own link card alongside quote", {
    $type: "app.bsky.embed.recordWithMedia#view",
    media: external("Art"),
    record: { $type: "app.bsky.embed.record#view", record: { $type: "app.bsky.embed.record#viewBlocked" } },
  }, false],
];
for (const [name, embed, hasMedia] of mediaCases) {
  test(`media classification and filter: ${name}`, async () => {
    const input = post("Art", embed);
    const [unfiltered] = await collect([input], ["art"]);
    assert.equal(unfiltered.hasMedia, hasMedia);
    const filtered = await collect([input], ["art"], { mediaOnly: true });
    assert.equal(filtered.length, hasMedia ? 1 : 0);
  });
}

test("no terms exports all liked posts for downstream jq filtering", async () => {
  const results = await collect([post("Text"), post("Art", imageEmbed)], []);
  assert.equal(results.length, 2);
  assert.equal(results.filter(result => result.hasMedia).length, 1);
  assert.deepEqual(results[0].author, { did: "did:plc:writer", handle: "writer.example" });
});

for (const profile of ["writer.example", "WRITER.EXAMPLE", "did:plc:writer"]) {
  for (const mediaOnly of [false, true]) {
    test(`profile feed filters likes, authors, and terms: ${profile}, media=${mediaOnly}`, async () => {
      const calls = [];
      const progress = [];
      const unliked = post("Art", imageEmbed);
      const foreign = { ...post("Art", imageEmbed), author: { did: "did:plc:someone", handle: "someone.example" }, viewer: { like: "at://me/like/foreign" } };
      const unrelated = { ...post("Unrelated", imageEmbed), viewer: { like: "at://me/like/unrelated" } };
      const matching = { ...post("Art", imageEmbed), viewer: { like: "at://me/like/matching" } };
      if (profile.startsWith("did:")) matching.author.handle = "renamed.example";
      const pages = [
        { feed: [unliked, foreign, unrelated].map(post => ({ post })), cursor: "next" },
        { feed: [{ post: matching }] },
      ];
      const agent = {
        getActorLikes: () => assert.fail("A profile search must use the author's feed"),
        getAuthorFeed: async args => {
          calls.push(args);
          return { data: pages.shift() };
        },
      };
      const results = await Array.fromAsync(searchLikes(agent, "me.example", ["art"],
        (...counts) => progress.push(counts), { profile, mediaOnly }));
      assert.equal(results.length, 1);
      assert.equal(results[0].text, "Art");
      assert.equal(results[0].author.did, "did:plc:writer");
      assert.equal(results[0].hasMedia, true);
      assert.deepEqual(calls, [undefined, "next"].map(cursor => ({
        actor: profile, filter: mediaOnly ? "posts_with_media" : "posts_with_replies",
        includePins: false, limit: 100, cursor,
      })));
      assert.deepEqual(progress, [[3, 0], [4, 1]]);
    });
  }
}

const authorScope = "rpc:app.bsky.feed.getAuthorFeed?aud=did:web:api.bsky.app%23bsky_appview";
const likesScope = "rpc:app.bsky.feed.getActorLikes?aud=did:web:api.bsky.app%23bsky_appview";
for (const [name, scopes, expected] of [
  ["old gallery-only session requires reauthorization for the new OAuth client ID", `atproto ${authorScope}`, false],
  ["likes permission alone does not match this client's permissions", `atproto ${likesScope}`, false],
  ["both permissions can be restored", `atproto ${authorScope} ${likesScope}`, true],
  ["scope order does not affect restoration", `${likesScope} atproto ${authorScope}`, true],
  ["wrong audience cannot be restored", `atproto ${authorScope} rpc:app.bsky.feed.getActorLikes?aud=other`, false],
  ["missing permissions cannot be restored", "atproto", false],
]) {
  test(name, () => assert.equal(canRestoreSession(scopes), expected));
}
