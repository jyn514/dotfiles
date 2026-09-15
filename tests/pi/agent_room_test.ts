import { describe, expect, test } from "bun:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import agentRoom, {
  prepareAgentRoomRequest,
  requestAgentRoom,
} from "../../config/agents/pi/pi-extensions/agent-room";

const ROOM = "http://127.0.0.1:3000/r/example.capability";

function response(body: string, status = 200, statusText = "OK"): Response {
  return new Response(body, { status, statusText });
}

describe("agent-room request construction", () => {
  test("uses the exact capability URL for inspection", () => {
    const supplied = `${ROOM}/`;
    const prepared = prepareAgentRoomRequest({ url: supplied, action: "inspect" });
    expect(prepared.url).toBe(supplied);
    expect(prepared.init.method).toBe("GET");
    expect(new Headers(prepared.init.headers).get("Accept"))
      .toBe("text/markdown, application/json;q=0.9");
  });

  test("encodes arbitrary message text as JSON", () => {
    const prepared = prepareAgentRoomRequest({
      url: ROOM,
      action: "send",
      text: "quote: '\"'\nsecond line",
    });
    expect(prepared.url).toBe(`${ROOM}/messages`);
    expect(prepared.init.method).toBe("POST");
    expect(prepared.init.body).toBe(JSON.stringify({ text: "quote: '\"'\nsecond line" }));
    expect(new Headers(prepared.init.headers).get("Content-Type")).toBe("application/json");
  });

  test("builds bounded reads, waits, and close requests", () => {
    expect(prepareAgentRoomRequest({ url: `${ROOM}/`, action: "read", since: 7 }).url)
      .toBe(`${ROOM}/messages?since=7`);
    expect(prepareAgentRoomRequest({ url: ROOM, action: "wait", since: 7 }).url)
      .toBe(`${ROOM}/messages?since=7&wait=180`);
    expect(prepareAgentRoomRequest({
      url: ROOM,
      action: "wait",
      since: 7,
      waitSeconds: 300,
    }).url).toBe(`${ROOM}/messages?since=7&wait=300`);

    const close = prepareAgentRoomRequest({ url: `${ROOM}/`, action: "close" });
    expect(close.url).toBe(`${ROOM}/close`);
    expect(close.init.method).toBe("POST");
  });

  test("rejects ambiguous or incomplete requests before network access", () => {
    expect(() => prepareAgentRoomRequest({ url: "file:///tmp/room", action: "inspect" }))
      .toThrow("HTTP or HTTPS");
    expect(() => prepareAgentRoomRequest({ url: `${ROOM}?since=1`, action: "inspect" }))
      .toThrow("query or fragment");
    expect(() => prepareAgentRoomRequest({ url: ROOM, action: "send" }))
      .toThrow("send requires text");
    expect(() => prepareAgentRoomRequest({ url: ROOM, action: "wait" }))
      .toThrow("wait requires since");
    expect(() => prepareAgentRoomRequest({
      url: ROOM,
      action: "wait",
      since: 0,
      waitSeconds: 301,
    })).toThrow("1 through 300");
  });
});

describe("agent-room HTTP behavior", () => {
  test("passes cancellation through and preserves protocol statuses", async () => {
    const controller = new AbortController();
    let observedSignal: AbortSignal | null | undefined;
    const result = await requestAgentRoom(
      { url: ROOM, action: "wait", since: 4, waitSeconds: 120 },
      controller.signal,
      async (_url, init) => {
        observedSignal = init?.signal;
        return response('{"messages":[],"closed":false}', 409, "Conflict");
      },
    );

    expect(observedSignal).toBe(controller.signal);
    expect(result).toEqual({
      action: "wait",
      status: 409,
      statusText: "Conflict",
      ok: false,
      body: '{"messages":[],"closed":false}',
      truncated: false,
    });
  });

  test("registers one stateless tool with close authorization guidance", async () => {
    type RegisteredTool = {
      name: string;
      description: string;
      promptGuidelines: string[];
      execute: (...args: never[]) => Promise<unknown>;
    };
    const tools: RegisteredTool[] = [];
    agentRoom({
      registerTool(tool: RegisteredTool) {
        tools.push(tool);
      },
    } as unknown as ExtensionAPI);

    expect(tools).toHaveLength(1);
    expect(tools[0].name).toBe("agent_room");
    expect(tools[0].description).toContain("exact capability URL");
    expect(tools[0].promptGuidelines.join(" ")).toContain("explicitly authorizes");
  });
});
