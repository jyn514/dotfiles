// Validate imports through the locked Pi SDK's real session loader and tree APIs.
import { SessionManager } from "@earendil-works/pi-coding-agent";

const text = (content) => typeof content === "string"
  ? content : content.filter((part) => part.type === "text").map((part) => part.text).join("\n");
const messages = (entries) => entries.filter((entry) => entry.type === "message" || entry.type === "custom_message")
  .map((entry) => text(entry.type === "message" ? entry.message.content : entry.content));
const inspect = (file) => {
  const session = SessionManager.open(file);
  const paths = [];
  const visit = (node) => {
    if (node.children.length === 0) paths.push(messages(session.getBranch(node.entry.id)));
    for (const child of node.children) visit(child);
  };
  for (const root of session.getTree()) visit(root);
  return {
    active: messages(session.getBranch()),
    context: session.buildSessionContext().messages.map((message) => text(message.content)),
    roles: session.buildSessionContext().messages.map((message) => message.role),
    toolCalls: session.buildSessionContext().messages.filter((message) => message.role === "assistant")
      .flatMap((message) => message.content.filter((block) => block.type === "toolCall")),
    toolResults: session.buildSessionContext().messages.filter((message) => message.role === "toolResult"),
    paths,
    labels: session.getEntries().filter((entry) => entry.type === "label").map((entry) => entry.label),
  };
};
console.log(JSON.stringify(process.argv.slice(2).map(inspect)));
