import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const source = await readFile(new URL("../assets/gallery.js", import.meta.url), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

// Run the complete gallery script with fixture fetch/document implementations.
// This checks image construction, not browser or assistive-technology behavior.
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
  }
  append(child) {
    this.children.push(child);
  }
}

const cases = [
  {
    name: "first image keeps its own author description",
    embed: { images: [
      { thumb: "https://fixture.invalid/first-thumb", fullsize: "https://fixture.invalid/first-full", alt: "A fox & an umbrella.\n雨" },
      { thumb: "https://fixture.invalid/second", alt: "Not the selected image" },
    ] },
    src: "https://fixture.invalid/first-thumb", alt: "A fox & an umbrella.\n雨",
  },
  {
    name: "record-with-media wrapper keeps the image description",
    embed: { $type: "app.bsky.embed.recordWithMedia#view", media: {
      $type: "app.bsky.embed.images#view",
      images: [{ thumb: "https://fixture.invalid/wrapped", alt: "Three boxes linked by arrows" }],
    } },
    src: "https://fixture.invalid/wrapped", alt: "Three boxes linked by arrows",
  },
  {
    name: "fullsize fallback keeps the same image description",
    embed: { images: [{ fullsize: "https://fixture.invalid/full", alt: "Full image description" }] },
    src: "https://fixture.invalid/full", alt: "Full image description",
  },
  {
    name: "empty author description stays empty",
    embed: { images: [{ thumb: "https://fixture.invalid/empty", alt: "" }] },
    src: "https://fixture.invalid/empty", alt: "",
  },
  {
    name: "missing author description stays empty",
    embed: { images: [{ thumb: "https://fixture.invalid/missing" }] },
    src: "https://fixture.invalid/missing", alt: "",
  },
  {
    name: "non-string description is not coerced",
    embed: { images: [{ thumb: "https://fixture.invalid/invalid", alt: 42 }] },
    src: "https://fixture.invalid/invalid", alt: "",
  },
  {
    name: "video thumbnail keeps precedence without an inferred description",
    embed: { thumbnail: "https://fixture.invalid/video", alt: "Not an image description", media: {
      images: [{ thumb: "https://fixture.invalid/ignored", alt: "Ignored" }],
    } },
    src: "https://fixture.invalid/video", alt: "",
  },
  {
    name: "external description is not used as image alt",
    embed: { external: { thumb: "https://fixture.invalid/external", description: "Not an image description" } },
    src: "https://fixture.invalid/external", alt: "",
  },
  { name: "missing embed renders only the post text", embed: null },
  {
    name: "missing first image URL does not select another preview",
    embed: { images: [{ alt: "Unavailable" }, { thumb: "https://fixture.invalid/ignored", alt: "Ignored" }], thumbnail: "https://fixture.invalid/also-ignored" },
  },
  {
    name: "empty thumbnail does not select fullsize",
    embed: { images: [{ thumb: "", fullsize: "https://fixture.invalid/ignored", alt: "Ignored" }] },
  },
  {
    name: "empty image list falls through to wrapped media",
    embed: { images: [], media: { images: [{ thumb: "https://fixture.invalid/nested", alt: "Nested image" }] } },
    src: "https://fixture.invalid/nested", alt: "Nested image",
  },
];

for (const fixture of cases) {
  test(fixture.name, async () => {
    const summary = new Element("p");
    const posts = new Element("main");
    const document = {
      createElement: tag => new Element(tag),
      querySelector: selector => ({ "#summary": summary, "#posts": posts })[selector],
    };
    // Two posts protect both author text and the existing empty-text fallback.
    const input = ["Post text", ""].map(text => ({
      url: "https://fixture.invalid/post", text, embed: fixture.embed,
    }));
    const fetch = async path => {
      assert.equal(path, "/posts.json");
      return { ok: true, json: async () => JSON.parse(JSON.stringify(input)) };
    };
    await new AsyncFunction("fetch", "document", source)(fetch, document);
    assert.equal(summary.textContent, "2 liked media posts");
    assert.equal(posts.children.length, 2);
    for (const [index, article] of posts.children.entries()) {
      assert.equal(article.tagName, "article");
      assert.equal(article.children.length, 1);
      const [link] = article.children;
      assert.equal(link.tagName, "a");
      assert.equal(link.href, input[index].url);
      assert.equal(link.target, "_blank");
      assert.equal(link.rel, "noopener noreferrer");
      assert.equal(link.children.length, fixture.src ? 2 : 1);
      const text = link.children.at(-1);
      assert.equal(text.tagName, "p");
      assert.equal(text.textContent, input[index].text || "View post");
      if (fixture.src) {
        const image = link.children[0];
        assert.equal(image.tagName, "img");
        assert.equal(image.src, fixture.src);
        assert.equal(image.loading, "lazy");
        assert.equal(image.alt, fixture.alt);
      }
    }
  });
}
