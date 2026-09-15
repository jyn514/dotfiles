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
  test("builds immediate and bounded incremental observations", () => {
    expect(prepareAgentRoomRequest({ url: `${ROOM}/`, action: "observe", since: 7 }).url)
      .toBe(`${ROOM}/messages?since=7`);
    expect(prepareAgentRoomRequest({
      url: ROOM,
      action: "observe",
      since: 7,
      waitSeconds: 300,
    }).url).toBe(`${ROOM}/messages?since=7&wait=300`);
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

  test("builds close requests", () => {
    const close = prepareAgentRoomRequest({ url: `${ROOM}/`, action: "close" });
    expect(close.url).toBe(`${ROOM}/close`);
    expect(close.init.method).toBe("POST");
  });

  test("rejects ambiguous or incomplete requests before network access", () => {
    expect(() => prepareAgentRoomRequest({ url: "file:///tmp/room", action: "observe" }))
      .toThrow("HTTP or HTTPS");
    expect(() => prepareAgentRoomRequest({ url: `${ROOM}?since=1`, action: "observe" }))
      .toThrow("query or fragment");
    expect(() => prepareAgentRoomRequest({ url: ROOM, action: "send" }))
      .toThrow("send requires text");
    expect(() => prepareAgentRoomRequest({
      url: ROOM,
      action: "observe",
      waitSeconds: 301,
    })).toThrow("0 through 300");
  });
});

describe("agent-room HTTP behavior", () => {
  test("initial observation includes instructions and normalized transcript state", async () => {
    const calls: string[] = [];
    const result = await requestAgentRoom(
      { url: ROOM, action: "observe", since: 0 },
      undefined,
      async (url) => {
        calls.push(String(url));
        return calls.length === 1
          ? response("# Room instructions")
          : response('{"messages":[{"id":4,"text":"hello"}],"closed":false}');
      },
    );

    expect(calls).toEqual([ROOM, `${ROOM}/messages?since=0`]);
    expect(JSON.parse(result.body)).toEqual({
      instructions: "# Room instructions",
      status: "updated",
      latest: 4,
      closed: false,
      messages: [{ id: 4, text: "hello" }],
    });
  });

  test("reports truncated initial instructions instead of presenting them as complete", async () => {
    const oversized = `${"x".repeat(200_000)}\n`;
    const result = await requestAgentRoom(
      { url: ROOM, action: "observe", since: 0 },
      undefined,
      async () => response(oversized),
    );

    expect(result.truncated).toBe(true);
    expect(result.body.length).toBeLessThan(oversized.length);
  });

  test("incremental observation omits instructions and reports timeout", async () => {
    const controller = new AbortController();
    let observedSignal: AbortSignal | null | undefined;
    const result = await requestAgentRoom(
      { url: ROOM, action: "observe", since: 4, waitSeconds: 120 },
      controller.signal,
      async (_url, init) => {
        observedSignal = init?.signal;
        return response('{"messages":[],"closed":false}');
      },
    );

    expect(observedSignal).toBe(controller.signal);
    expect(JSON.parse(result.body)).toEqual({
      status: "timeout",
      latest: 4,
      closed: false,
      messages: [],
    });
  });

  test("send confirms creation without returning the transcript", async () => {
    const calls: string[] = [];
    const result = await requestAgentRoom(
      { url: ROOM, action: "send", text: "hello" },
      undefined,
      async (url) => {
        calls.push(String(url));
        return calls.length === 1
          ? response('{"id":13}', 201, "Created")
          : response('{"messages":[{"id":13,"text":"hello"}],"closed":false}');
      },
    );

    expect(calls).toEqual([`${ROOM}/messages`, `${ROOM}/messages?since=12`]);
    expect(result.status).toBe(201);
    expect(JSON.parse(result.body)).toEqual({ id: 13, confirmed: true });
  });

  test("send failures remain compact", async () => {
    const malformed = await requestAgentRoom(
      { url: ROOM, action: "send", text: "hello" },
      undefined,
      async () => response(JSON.stringify({ unexpected: "x".repeat(10_000) }), 201, "Created"),
    );
    expect(JSON.parse(malformed.body)).toEqual({
      id: null,
      confirmed: false,
      error: "creation response did not contain an integer message ID",
    });

    let calls = 0;
    const failedReadback = await requestAgentRoom(
      { url: ROOM, action: "send", text: "hello" },
      undefined,
      async () => ++calls === 1
        ? response('{"id":13}', 201, "Created")
        : response("large diagnostic omitted", 500, "Failure"),
    );
    expect(JSON.parse(failedReadback.body)).toEqual({
      id: 13,
      confirmed: false,
      error: "read-back failed: HTTP 500",
    });
  });

  test("preserves protocol failures", async () => {
    const result = await requestAgentRoom(
      { url: ROOM, action: "observe", since: 4 },
      undefined,
      async () => response('{"messages":[],"closed":false}', 409, "Conflict"),
    );

    expect(result).toEqual({
      action: "observe",
      status: 409,
      statusText: "Conflict",
      ok: false,
      body: '{"messages":[],"closed":false}',
      truncated: false,
    });
  });

  test("registers one stateless tool with incremental and close guidance", async () => {
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
    expect(tools[0].description).toContain("incremental messages");
    expect(tools[0].promptGuidelines.join(" ")).toContain("explicitly authorizes");
  });
});
