import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const COMPLETE_READING_POLICY = `- When working on pi topics, read the docs and examples, and follow .md cross-references before implementing
- Always read pi .md files completely and follow links to related docs (e.g., tui.md for TUI API details)`;

const TASK_DIRECTED_POLICY = "- Before implementing Pi-specific behavior, read the relevant documentation sections. Check relevant shipped examples for a reusable starting point. Follow references when they define an API or constraint needed for the task. Read whole files only when the task requires understanding them as a whole.";

export default function taskDirectedDocs(pi: ExtensionAPI): void {
  pi.on("before_agent_start", (event) => {
    // Pi exposes custom section inputs, not the generated docs body. Preserve
    // its paths and topic routes; the native test checks this formatting dependency.
    const docs = event.systemPrompt.match(/^<docs>\n([\s\S]*?)\n<\/docs>$/m)?.[1];
    if (docs === undefined) return;
    const updated = docs.replace(COMPLETE_READING_POLICY, TASK_DIRECTED_POLICY);
    if (updated !== docs) event.systemPromptOptions.sections.docs = updated;
  });
}
