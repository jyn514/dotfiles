import { createServer } from "node:http";
import { once } from "node:events";
import { setDefaultResultOrder } from "node:dns";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";
const { createIpv4Fetch } = await import(pathToFileURL(process.argv[2]));

setDefaultResultOrder("ipv6first");
// Reproduce Pi replacing the global dispatcher before a model request.
const { Agent, setGlobalDispatcher } = createRequire(import.meta.url)("undici");
setGlobalDispatcher(new Agent({ connect: { family: 6, autoSelectFamily: false } }));
const ipv4 = createIpv4Fetch(process.argv[1]);
const server = createServer((request, response) => {
  if (request.url === "/drop") {
    response.write("partial");
    setTimeout(() => response.socket.destroy(), 20);
  } else response.end(request.socket.remoteFamily);
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
try {
  const response = await ipv4.fetch(`http://localhost:${server.address().port}`);
  console.log(await response.text());
  const dropped = await ipv4.fetch(`http://localhost:${server.address().port}/drop`);
  await assert.rejects(dropped.text());
} finally {
  server.closeAllConnections();
  server.close();
  await ipv4.close();
}
