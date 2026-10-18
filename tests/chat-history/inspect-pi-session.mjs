// Validate imports through the locked Pi SDK's real session loader and tree APIs.
import { SessionManager } from "@earendil-works/pi-coding-agent";

const text = (content) => typeof content === "string"
  ? content : content.filter((part) => part.type === "text").map((part) => part.text).join("\n");
const messages = (entries) => entries.filter((entry) => entry.type === "message")
  .map((entry) => text(entry.message.content));
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
    paths,
    labels: session.getEntries().filter((entry) => entry.type === "label").map((entry) => entry.label),
  };
};
console.log(JSON.stringify(process.argv.slice(2).map(inspect)));
