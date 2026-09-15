import { expect, test } from "bun:test";

test("Bun test runtime matches the container libc", () => {
  expect(Bun.version).toMatch(/^1\.3\./);
});
