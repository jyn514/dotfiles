import { appendFileSync, readFileSync } from "node:fs";
import { createInterface } from "node:readline";

const fixture = JSON.parse(readFileSync(process.env.CODEX_HISTORY_FIXTURE, "utf8"));
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  appendFileSync(process.env.CODEX_HISTORY_REQUESTS, JSON.stringify(request) + "\n");
  if (request.id === undefined) continue;
  const reply = result => console.log(JSON.stringify({ id: request.id, result }));
  if (request.method === "initialize") reply({});
  else if (request.method === "thread/read") reply({ thread: fixture.thread });
  else if (request.method === "thread/turns/list") {
    if (fixture.error) {
      console.log(JSON.stringify({ id: request.id, error: { code: -32600, message: fixture.error } }));
    } else {
      const index = request.params.cursor ? Number(request.params.cursor) : 0;
      reply(fixture.pages[index]);
    }
  } else {
    console.log(JSON.stringify({ id: request.id, error: { code: -32601, message: `unexpected method ${request.method}` } }));
  }
}
