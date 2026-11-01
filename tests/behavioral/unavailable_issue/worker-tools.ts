import { cwd, relocateBashOutput, type Sandbox } from "./runtime.ts";

/** The same native Pi tools and Docker operations serve both launch routes. */
export function workerTools(sdk: any, sandbox: Pick<Sandbox, "io" | "shell" | "infrastructureErrors">) {
  const readFile = (path: string) => sandbox.io("read", [path]);
  const writeFile = async (path: string, text: string) => { await sandbox.io("write", [path], text); };
  const tools = [
    sdk.createReadToolDefinition(cwd, { operations: { readFile,
      access: async (path: string) => { await sandbox.io("access", [path, "r"]); } } }),
    sdk.createEditToolDefinition(cwd, { operations: { readFile, writeFile,
      access: async (path: string) => { await sandbox.io("access", [path, "rw"]); } } }),
    sdk.createWriteToolDefinition(cwd, { operations: { writeFile,
      mkdir: async (path: string) => { await sandbox.io("mkdir", [path]); } } }),
    sdk.createBashToolDefinition(cwd, { exposeSessionEnvironment: false, operations: {
      exec: async (command: string, _workdir: string, options: any) => {
        const seconds = Math.max(1, Math.min(120, options.timeout ?? 60));
        const result = await sandbox.shell(command, seconds, options.signal);
        options.onData(Buffer.from(result.output));
        return { exitCode: result.exit_code };
      },
    } }),
  ];
  const bash = tools.find(tool => tool.name === "bash")!;
  const execute = bash.execute.bind(bash);
  bash.execute = async (id: string, input: any, signal: AbortSignal | undefined, _update: any, context: any) => {
    // Native updates can advertise a host spill path before it has been relocated.
    const result = await execute(id, input, signal, undefined, context);
    try { return await relocateBashOutput(result, (path, content) => sandbox.io("write", [path], content)); }
    catch (error) { sandbox.infrastructureErrors.push(String(error)); throw error; }
  };
  for (const tool of tools) {
    const execute = tool.execute.bind(tool);
    tool.execute = (id: string, input: any, signal: AbortSignal | undefined, update: any, context: any) =>
      execute(id, input, signal, update, context ? Object.create(context, { cwd: { value: cwd, enumerable: true } }) : undefined);
  }
  return tools;
}
