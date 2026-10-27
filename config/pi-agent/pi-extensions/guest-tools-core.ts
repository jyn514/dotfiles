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
  paths: Readonly<Record<string, string>>,
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
