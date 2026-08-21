import { readFile, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { homedir } from "node:os";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ContextFile = { path: string; content: string };
type CacheEntry = { mtimeMs: number; size: number; content: string };

const cache = new Map<string, CacheEntry>();
const decoder = new TextDecoder("utf-8", { fatal: true });

function isWithin(path: string, root: string): boolean {
  const suffix = relative(root, path);
  return suffix === "" || (!suffix.startsWith("..") && !isAbsolute(suffix));
}

async function canonicalDirectory(path: string): Promise<string> {
  return realpath(path);
}

async function readUtf8(path: string): Promise<string> {
  const metadata = await stat(path);
  if (!metadata.isFile()) throw new Error(`instruction include is not a file: ${path}`);

  const cached = cache.get(path);
  if (cached?.mtimeMs === metadata.mtimeMs && cached.size === metadata.size) return cached.content;

  let content: string;
  try {
    content = decoder.decode(await readFile(path));
  } catch (error) {
    throw new Error(`instruction include is not valid UTF-8: ${path}`, { cause: error });
  }
  cache.set(path, { mtimeMs: metadata.mtimeMs, size: metadata.size, content });
  return content;
}

function includesIn(content: string): string[] {
  const includes: string[] = [];
  let fence: string | undefined;

  for (const line of content.split(/\r?\n/)) {
    const opening = line.match(/^\s*(`{3,}|~{3,})/);
    if (opening) {
      const marker = opening[1][0];
      if (!fence) fence = marker;
      else if (fence === marker) fence = undefined;
      continue;
    }
    if (fence) continue;

    const directive = line.match(/^\s*@([^\s].*?)\s*$/);
    if (directive) includes.push(directive[1]);
  }
  return includes;
}

async function expandFile(
  path: string,
  roots: string[],
  stack: string[],
): Promise<string> {
  let canonical: string;
  try {
    canonical = await realpath(path);
  } catch (error) {
    throw new Error(`instruction include does not exist: ${path}`, { cause: error });
  }

  if (!roots.some((root) => isWithin(canonical, root))) {
    throw new Error(`instruction include escapes allowed roots: ${path}`);
  }
  const cycleAt = stack.indexOf(canonical);
  if (cycleAt !== -1) {
    throw new Error(`instruction include cycle: ${[...stack.slice(cycleAt), canonical].join(" -> ")}`);
  }

  const content = await readUtf8(canonical);
  const children: string[] = [];
  for (const include of includesIn(content)) {
    const target = include.startsWith("~/")
      ? resolve(homedir(), include.slice(2))
      : resolve(dirname(canonical), include);
    children.push(await expandFile(target, roots, [...stack, canonical]));
  }

  return [`<!-- instruction include: ${canonical} -->`, content, ...children].join("\n\n");
}

export async function expandInstructionIncludes(
  contextFiles: ContextFile[],
  cwd: string,
): Promise<string[]> {
  const cwdRoot = await canonicalDirectory(cwd);
  const contextRoots = await Promise.all(
    contextFiles.map(async (file) => canonicalDirectory(dirname(file.path))),
  );
  const roots = [...new Set([cwdRoot, ...contextRoots])];
  const expanded: string[] = [];

  for (const contextFile of contextFiles) {
    for (const include of includesIn(contextFile.content)) {
      const target = include.startsWith("~/")
        ? resolve(homedir(), include.slice(2))
        : resolve(dirname(contextFile.path), include);
      expanded.push(await expandFile(target, roots, []));
    }
  }
  return expanded;
}

export default function instructionIncludes(pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event) => {
    const expanded = await expandInstructionIncludes(
      event.systemPromptOptions.contextFiles,
      event.systemPromptOptions.cwd,
    );
    if (expanded.length === 0) return;

    return {
      systemPrompt: `${event.systemPrompt}\n\n## Expanded instruction includes\n\n${expanded.join("\n\n")}`,
    };
  });
}
