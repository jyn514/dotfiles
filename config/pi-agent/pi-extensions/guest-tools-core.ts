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
