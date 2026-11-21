#!/usr/bin/env node
import { parseArgs } from "node:util";
import type { SearchFilters } from "./search.ts";

export type Options =
  | { mode: "gallery" }
  | ({ mode: "search"; terms: string[]; json: boolean } & SearchFilters);

const HELP = `Usage: search-bsky-likes [--profile HANDLE|DID] [--media-only] [--json] [TERM ...]
       search-bsky-likes

Search all posts liked by jyn.dev. Every term must occur, ignoring case,
in the post text, quoted post text, link URLs, or link-card titles/descriptions.
Quote a term containing spaces to match that phrase. Article bodies aren't fetched.
Search results print to the terminal; no browser gallery opens.

With no arguments, open the existing theotherhappyplace.bsky.social media gallery.
With filters or --json but no terms, list liked posts without a text restriction.

Options:
  --profile HANDLE|DID  Only liked posts written by this author (optional @ prefix).
  --media-only          Only posts with attached images/video, including galleries.
                        Link previews and media inside quoted posts don't count.
  --json                Print one JSON object per matching post, including author
                        and hasMedia fields, instead of readable text.
  -h, --help            Show help without authentication or network access.

Examples:
  search-bsky-likes education
  search-bsky-likes education AI
  search-bsky-likes --json credential
  search-bsky-likes --profile theotherhappyplace.bsky.social --media-only
  search-bsky-likes --json | jq 'select(.hasMedia)'

Search requires read-only access to your liked-post feed. The first search
opens Bluesky authorization in your browser; later runs reuse the saved session.
Upgrading an old gallery session requires authorization again.
`;

export function parseOptions(args: string[]): Options | "help" {
  const { values, positionals } = parseArgs({
    args,
    allowPositionals: true,
    options: {
      help: { type: "boolean", short: "h" },
      json: { type: "boolean" },
      profile: { type: "string" },
      "media-only": { type: "boolean" },
    },
  });
  if (values.help) return "help";
  if (positionals.some(term => term.trim() === "")) {
    throw new Error("Search terms must not be empty.");
  }
  const profile = values.profile?.replace(/^@/, "");
  if (profile !== undefined && profile.trim() === "") {
    throw new Error("--profile requires an author handle or DID.");
  }
  if (positionals.length === 0 && profile === undefined && !values["media-only"] && !values.json) {
    return { mode: "gallery" };
  }
  return {
    mode: "search",
    terms: positionals,
    json: values.json ?? false,
    ...(profile !== undefined ? { profile } : {}),
    ...(values["media-only"] ? { mediaOnly: true } : {}),
  };
}

if (import.meta.main) {
  try {
    const options = parseOptions(process.argv.slice(2));
    if (options === "help") {
      console.log(HELP);
    } else {
      const { main } = await import("./search-bsky-likes.ts");
      await main(options);
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    console.error("See search-bsky-likes --help for usage.");
    process.exitCode = 1;
  }
}
