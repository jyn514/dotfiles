type PathMappings = Readonly<Record<string, string>>;

export function parsePiResourcePaths(raw: string | undefined): Record<string, string> {
  const paths = JSON.parse(raw || "{}");
  if (!paths || typeof paths !== "object" || Array.isArray(paths) ||
    Object.entries(paths).some(([hostPath, guestPath]) =>
      !hostPath.startsWith("/") || typeof guestPath !== "string" || !guestPath.startsWith("/"))) {
    throw new Error("Pi resource path mapping is invalid");
  }
  return paths;
}

export function rewritePiResourcePaths(
  prompt: string,
  paths: PathMappings,
): string {
  return Object.entries(paths)
    .sort(([left], [right]) => right.length - left.length)
    .reduce((rewritten, [hostPath, guestPath]) => {
      const escaped = hostPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return rewritten.replace(
        new RegExp(`${escaped}(?=$|[/\\\\\\r\\n\\s"'<>(),;:!?])`, "g"),
        () => guestPath,
      );
    }, prompt);
}

function resourcePath(value: string, paths: PathMappings): string {
  // Translate once. A host path such as /home/user/src can itself contain
  // the guest prefix /src; repeated text replacement would corrupt it.
  for (const [from, to] of Object.entries(paths).sort(([left], [right]) => right.length - left.length)) {
    if (value === from || value.startsWith(from + "/")) return to + value.slice(from.length);
  }
  return value;
}

export function sessionToolInputToHost(
  tool: string, input: Record<string, unknown>, paths: PathMappings,
): void {
  const field = tool === "read_session" ? "sessionFile" : tool === "search_sessions" ? "cwd" : undefined;
  if (!field || typeof input[field] !== "string" || !input[field].startsWith("/")) return;
  const inverse = Object.fromEntries(Object.entries(paths).map(([host, guest]) => [guest, host]));
  input[field] = resourcePath(input[field], inverse);
}

function metadata(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

// Project only the session tools' path metadata. Snippets, historical message
// text, and opaque cursors are evidence, not paths in the active environment.
export function sessionToolMetadataToGuest(value: unknown, paths: PathMappings): unknown {
  const original = metadata(value);
  if (!original) return value;
  const result = { ...original };
  for (const field of ["sessionFile", "sessionCwd"]) {
    if (typeof result[field] === "string") result[field] = resourcePath(result[field], paths);
  }
  for (const field of ["hits", "versions"]) {
    if (Array.isArray(result[field])) {
      result[field] = result[field].map(item => sessionToolMetadataToGuest(item, paths));
    }
  }
  return result;
}

export function sessionToolTextToGuest(
  tool: string, text: string, details: unknown, paths: PathMappings,
): string {
  if (text.startsWith(`${tool} failed:`)) return rewritePiResourcePaths(text, paths);
  if (tool === "search_sessions") {
    try { return JSON.stringify(sessionToolMetadataToGuest(JSON.parse(text), paths), null, 2); }
    catch { return text; }
  }
  if (tool !== "read_session") return text;
  const versions = metadata(details)?.versions;
  if (Array.isArray(versions)) {
    for (const item of versions) {
      const version = metadata(item);
      if (!version || typeof version.index !== "number" || typeof version.timestamp !== "string" ||
        typeof version.sessionCwd !== "string" || typeof version.sessionFile !== "string") continue;
      const title = `${version.index}. ${version.timestamp} — cwd: `;
      // Match the two metadata lines together; a preview can itself contain a
      // line resembling a path field and must remain unchanged.
      const original = `${title}${version.sessionCwd}\n   sessionFile: ${JSON.stringify(version.sessionFile)}`;
      const projected = `${title}${resourcePath(version.sessionCwd, paths)}\n   sessionFile: ${JSON.stringify(resourcePath(version.sessionFile, paths))}`;
      text = text.replace(original, () => projected);
    }
    return text;
  }
  // Only the first line belongs to the reader. All later text may be quoted
  // transcript content, even if it resembles the reader's header format.
  return text.replace(/^(# Session [^\n]*? — cwd: )([^\n]*?)( — started: [^\n]*)(?=\n|$)/,
    (_header, prefix: string, cwd: string, suffix: string) => prefix + resourcePath(cwd, paths) + suffix);
}
