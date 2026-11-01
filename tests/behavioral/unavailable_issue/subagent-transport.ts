import { randomUUID } from "node:crypto";
import { rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { processOutput } from "./runtime.ts";

export type GuestCall = (command: string, signal: AbortSignal | undefined,
  onData: (data: Buffer) => void) => Promise<{ exitCode: number | null }>;

export const quoteArgument = (value: string) => `'${value.replaceAll("'", "'\\''")}'`;

/** Reuse the parent's admitted guest attachment, including its Docker gateway.
 * Input bytes travel through an owned shared scratch file, never shell syntax or credentials.
 * The guest's user_bash protocol streams raw bytes without native tool truncation.
 */
export function guestExecutor(call: GuestCall, scratch: string, toGuest: (path: string) => string): typeof processOutput {
  return async (command, args, input, signal, onData) => {
    const inputPath = input === undefined ? undefined : join(scratch, `stdin-${randomUUID()}`);
    const controller = new AbortController();
    const chunks: Buffer[] = [];
    let size = 0;
    let overflow = false;
    try {
      if (inputPath) await writeFile(inputPath, input!, { flag: "wx", mode: 0o600 });
      const source = inputPath ? toGuest(inputPath) : "/dev/null";
      const commandLine = `${[command, ...args].map(quoteArgument).join(" ")} < ${quoteArgument(source)}`;
      const result = await call(commandLine,
        signal ? AbortSignal.any([signal, controller.signal]) : controller.signal,
        data => {
          size += data.length;
          if (size > 64 * 1024 * 1024) { overflow = true; controller.abort(); return; }
          if (onData) onData(data); else chunks.push(data);
        });
      if (overflow) throw new Error("Guest process output exceeds 64 MiB");
      const output = Buffer.concat(chunks);
      if (result.exitCode !== 0) throw Object.assign(
        new Error(`${command} exited ${result.exitCode}: ${output.toString().trim()}`),
        { exitCode: result.exitCode ?? 1 });
      return output;
    } finally {
      if (inputPath) await rm(inputPath, { force: true });
    }
  };
}
