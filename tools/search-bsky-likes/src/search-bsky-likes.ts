#!/usr/bin/env node
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { spawn } from "node:child_process";

import { Agent, AppBskyFeedPost } from "@atproto/api";
import {
  NodeOAuthClient,
  buildAtprotoLoopbackClientMetadata,
  type NodeSavedSession,
  type NodeSavedState,
} from "@atproto/oauth-client-node";

const ME = "jyn.dev";
const TARGET = "theotherhappyplace.bsky.social";
type CallbackUrl =
  | "http://127.0.0.1/callback"
  | `http://127.0.0.1:${number}/callback`;

const REGISTERED_CALLBACK_URL: CallbackUrl = "http://127.0.0.1/callback";
const REQUIRED_RPC_SCOPE =
  "rpc:app.bsky.feed.getAuthorFeed?aud=did:web:api.bsky.app%23bsky_appview";
const SCOPE = `atproto ${REQUIRED_RPC_SCOPE}`;
const STORE_PATH = join(
  process.env.XDG_STATE_HOME ?? join(homedir(), ".local", "state"),
  "search-bsky-likes",
  "oauth.json",
);

type StoreData = {
  states: Record<string, NodeSavedState>;
  sessions: Record<string, NodeSavedSession>;
};

type StoreSection = keyof StoreData;

let pendingWrite = Promise.resolve();

async function loadStore(): Promise<StoreData> {
  try {
    return JSON.parse(await readFile(STORE_PATH, "utf8")) as StoreData;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { states: {}, sessions: {} };
    }
    throw error;
  }
}

async function updateStore(
  update: (data: StoreData) => void,
): Promise<void> {
  pendingWrite = pendingWrite.then(async () => {
    const data = await loadStore();
    update(data);
    await mkdir(dirname(STORE_PATH), { mode: 0o700, recursive: true });
    const temporaryPath = `${STORE_PATH}.${process.pid}.tmp`;
    await writeFile(temporaryPath, `${JSON.stringify(data)}\n`, { mode: 0o600 });
    await rename(temporaryPath, STORE_PATH);
  });
  return pendingWrite;
}

function sectionStore<Value>(section: StoreSection) {
  return {
    async set(key: string, value: Value): Promise<void> {
      await updateStore((data) => {
        (data[section] as Record<string, Value>)[key] = value;
      });
    },
    async get(key: string): Promise<Value | undefined> {
      return (await loadStore())[section][key] as Value | undefined;
    },
    async del(key: string): Promise<void> {
      await updateStore((data) => {
        delete data[section][key];
      });
    },
    async clear(): Promise<void> {
      await updateStore((data) => {
        data[section] = {};
      });
    },
  };
}

function createClient(
  callbackUrl: CallbackUrl = REGISTERED_CALLBACK_URL,
): NodeOAuthClient {
  const registeredMetadata = buildAtprotoLoopbackClientMetadata({
    scope: SCOPE,
    redirect_uris: [REGISTERED_CALLBACK_URL],
  });
  return new NodeOAuthClient({
    // RFC 8252 permits an ephemeral port when the registered loopback URI omits
    // one. Keep the client ID stable while giving this invocation its bound URI.
    clientMetadata: {
      ...registeredMetadata,
      redirect_uris: [callbackUrl],
    },
    stateStore: sectionStore<NodeSavedState>("states"),
    sessionStore: sectionStore<NodeSavedSession>("sessions"),
    requestLock: async (_key, fn) => fn(),
  });
}

function openBrowser(url: URL): void {
  const command = process.platform === "darwin" ? "open" : "xdg-open";
  const child = spawn(command, [url.href], {
    detached: true,
    stdio: "ignore",
  });
  child.on("error", () => {
    console.error(`Open this URL in a browser:\n${url.href}`);
  });
  child.unref();
}

async function authorize() {
  let client: NodeOAuthClient;
  let callbackUrl: CallbackUrl;
  const callback = Promise.withResolvers<
    Awaited<ReturnType<NodeOAuthClient["callback"]>>
  >();
  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", callbackUrl);
      if (url.pathname !== "/callback") {
        response.writeHead(404).end("Not found\n");
        return;
      }
      const result = await client.callback(url.searchParams, {
        redirect_uri: callbackUrl,
      });
      response.writeHead(200, { "content-type": "text/plain" });
      response.end("Authorization complete. You may close this window.\n");
      server.close();
      callback.resolve(result);
    } catch (error) {
      response.writeHead(500).end("Authorization failed.\n");
      server.close();
      callback.reject(error);
    }
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.removeListener("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Could not determine OAuth callback port");
  }

  callbackUrl = `http://127.0.0.1:${address.port}/callback`;
  client = createClient(callbackUrl);
  try {
    const url = await client.authorize(ME, {
      redirect_uri: callbackUrl,
      state: randomUUID(),
    });
    console.error("Waiting for Bluesky authorization in your browser...");
    openBrowser(url);
    return (await callback.promise).session;
  } catch (error) {
    server.close();
    throw error;
  }
}

async function restoreOrAuthorize() {
  const stored = await loadStore();
  const did = Object.keys(stored.sessions)[0];
  const grantedScopes = did
    ? stored.sessions[did].tokenSet.scope.split(" ")
    : [];
  if (did && grantedScopes.includes(REQUIRED_RPC_SCOPE)) {
    return createClient().restore(did);
  }
  if (did) {
    await updateStore((data) => {
      data.sessions = {};
      data.states = {};
    });
  }
  return authorize();
}

async function main(): Promise<void> {
  const session = await restoreOrAuthorize();
  const agent = new Agent(session);
  let postsScanned = 0;
  let likesFound = 0;
  let cursor: string | undefined;

  do {
    const page = await agent.getAuthorFeed({
      actor: TARGET,
      filter: "posts_with_media",
      limit: 100,
      cursor,
    });

    for (const item of page.data.feed) {
      const post = item.post;
      if (post.author.handle !== TARGET || !post.viewer?.like) continue;
      if (!AppBskyFeedPost.isRecord(post.record)) continue;
      const rkey = post.uri.slice(post.uri.lastIndexOf("/") + 1);
      console.log(`https://bsky.app/profile/${post.author.did}/post/${rkey}`);
      likesFound += 1;
    }

    postsScanned += page.data.feed.length;
    console.error(
      `scanned ${postsScanned} media posts; found ${likesFound} likes`,
    );
    cursor = page.data.cursor;
  } while (cursor);
}

await main();
