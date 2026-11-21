import {
  AppBskyEmbedExternal,
  AppBskyEmbedGallery,
  AppBskyEmbedImages,
  AppBskyEmbedVideo,
  AppBskyEmbedRecord,
  AppBskyEmbedRecordWithMedia,
  AppBskyFeedPost,
  AppBskyRichtextFacet,
  type Agent,
  type AppBskyFeedDefs,
} from "@atproto/api";

export type SearchLink = {
  url: string;
  title?: string;
  description?: string;
};

export type SearchFilters = {
  profile?: string;
  mediaOnly?: boolean;
};

export type SearchResult = {
  url: string;
  text: string;
  links: SearchLink[];
  author: { did: string; handle: string };
  hasMedia: boolean;
};

function isMediaEmbed(embed: AppBskyFeedDefs.PostView["embed"]): boolean {
  if (AppBskyEmbedImages.isView(embed)) return embed.images.length > 0;
  if (AppBskyEmbedVideo.isView(embed)) return true;
  if (AppBskyEmbedGallery.isView(embed)) return embed.items.some(AppBskyEmbedGallery.isViewImage);
  return false;
}

function hasAttachedMedia(embed: AppBskyFeedDefs.PostView["embed"]): boolean {
  return isMediaEmbed(AppBskyEmbedRecordWithMedia.isView(embed) ? embed.media : embed);
}

function searchablePost(post: AppBskyFeedDefs.PostView): SearchResult | undefined {
  if (!AppBskyFeedPost.isRecord(post.record)) return;
  const textParts: string[] = [];
  const links = new Map<string, SearchLink[]>();
  const embeds: Array<
    | AppBskyEmbedExternal.View
    | AppBskyEmbedRecord.View
    | AppBskyEmbedRecordWithMedia.View
    | { $type: string }
  > = post.embed ? [post.embed] : [];

  function addRecord(record: AppBskyFeedDefs.PostView["record"]): void {
    if (!AppBskyFeedPost.isRecord(record)) return;
    const validated = AppBskyFeedPost.validateRecord(record);
    if (!validated.success) return;
    textParts.push(validated.value.text);
    for (const facet of validated.value.facets ?? []) {
      for (const feature of facet.features) {
        if (AppBskyRichtextFacet.isLink(feature) && !links.has(feature.uri)) {
          links.set(feature.uri, [{ url: feature.uri }]);
        }
      }
    }
  }

  addRecord(post.record);
  while (embeds.length > 0) {
    const embed = embeds.pop();
    if (AppBskyEmbedExternal.isView(embed)) {
      const { uri, title, description } = embed.external;
      const previews = (links.get(uri) ?? []).filter(link => link.title !== undefined);
      if (!previews.some(link => link.title === title && link.description === description)) {
        previews.push({ url: uri, title, description });
      }
      links.set(uri, previews);
    } else if (AppBskyEmbedRecordWithMedia.isView(embed)) {
      embeds.push(embed.record, embed.media);
    } else if (
      AppBskyEmbedRecord.isView(embed) &&
      AppBskyEmbedRecord.isViewRecord(embed.record)
    ) {
      addRecord(embed.record.value);
      embeds.push(...(embed.record.embeds ?? []));
    }
  }

  const rkey = post.uri.slice(post.uri.lastIndexOf("/") + 1);
  return {
    url: `https://bsky.app/profile/${post.author.did}/post/${rkey}`,
    text: textParts.join("\n\n"),
    links: [...links.values()].flat(),
    author: { did: post.author.did, handle: post.author.handle },
    hasMedia: hasAttachedMedia(post.embed),
  };
}

/**
 * Stream liked-post matches; a later request failure leaves partial output.
 * A profile filter scans that author's feed and checks the authenticated viewer's
 * likes, rather than reading every liked post. Progress counts feed entries read.
 */
export async function* searchLikes(
  agent: Pick<Agent, "getActorLikes" | "getAuthorFeed">,
  actor: string,
  terms: string[],
  onPage: (scanned: number, matched: number) => void,
  filters: SearchFilters = {},
): AsyncGenerator<SearchResult> {
  const needles = terms.map(term => term.toLowerCase());
  let cursor: string | undefined;
  let scanned = 0;
  let matched = 0;
  do {
    const page = filters.profile
      ? await agent.getAuthorFeed({
        actor: filters.profile,
        filter: filters.mediaOnly ? "posts_with_media" : "posts_with_replies",
        includePins: false,
        limit: 100,
        cursor,
      })
      : await agent.getActorLikes({ actor, limit: 100, cursor });
    for (const { post } of page.data.feed) {
      scanned += 1;
      if (filters.profile) {
        const isAuthor = filters.profile.startsWith("did:")
          ? post.author.did === filters.profile
          : post.author.handle.toLowerCase() === filters.profile.toLowerCase();
        if (!isAuthor || !post.viewer?.like) continue;
      }
      const result = searchablePost(post);
      if (!result || (filters.mediaOnly && !result.hasMedia)) continue;
      const haystack = [
        result.text,
        ...result.links.flatMap(link => [link.url, link.title ?? "", link.description ?? ""]),
      ].join("\n").toLowerCase();
      if (needles.every(needle => haystack.includes(needle))) {
        matched += 1;
        yield result;
      }
    }
    onPage(scanned, matched);
    cursor = page.data.cursor;
  } while (cursor);
}

export function formatResult(result: SearchResult): string {
  const lines = [result.url, result.text];
  for (const link of result.links) {
    if (link.title) lines.push(link.title);
    lines.push(link.url);
    if (link.description) lines.push(link.description);
  }
  return lines.join("\n");
}
