import { writeFile } from "node:fs/promises";

export function createAllTools() {
  return {
    read: {
      async execute(_id, params) {
        return { content: [{ type: "text", text: `guest:${params.path}` }] };
      },
    },
    bash: {
      async execute(_id, _params, signal, onUpdate) {
        onUpdate({ content: [{ type: "text", text: "started" }] });
        await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
        await writeFile(process.env.CODEX_SANDBOX_CANCEL_MARKER, "cancelled");
        return { content: [{ type: "text", text: "cancelled" }] };
      },
    },
  };
}

export function createLocalBashOperations() {
  return {
    async exec(_command, _cwd, { onData }) {
      onData(Buffer.from("guest shell output"));
      return { exitCode: 3 };
    },
  };
}
