export function rewritePiResourcePaths(
  prompt: string,
  paths: Readonly<Record<string, string>>,
): string {
  return Object.entries(paths).reduce(
    (rewritten, [hostPath, guestPath]) => rewritten.replaceAll(hostPath, guestPath),
    prompt,
  );
}
