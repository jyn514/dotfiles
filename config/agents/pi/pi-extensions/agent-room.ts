import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  truncateHead,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";

export const AGENT_ROOM_ACTIONS = ["observe", "send", "close"] as const;
export type AgentRoomAction = typeof AGENT_ROOM_ACTIONS[number];

export interface AgentRoomRequest {
  url: string;
  action: AgentRoomAction;
  text?: string;
  since?: number;
  waitSeconds?: number;
}

export interface AgentRoomResult {
  action: AgentRoomAction;
  status: number;
  statusText: string;
  ok: boolean;
  body: string;
  truncated: boolean;
}

type Fetch = (input: string | URL, init?: RequestInit) => Promise<Response>;

type RoomMessage = { id: number; [key: string]: unknown };
type Transcript = { messages: RoomMessage[]; closed: boolean };

function capabilityUrl(rawUrl: string): string {
  const parsed = new URL(rawUrl);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Agent-room capability URL must use HTTP or HTTPS");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("Agent-room capability URL must not contain a query or fragment");
  }
  return rawUrl;
}

function roomEndpoint(capability: string, path: string): string {
  return `${capability}${capability.endsWith("/") ? "" : "/"}${path}`;
}

function validateInteger(name: string, value: number, minimum: number, maximum?: number): void {
  if (!Number.isInteger(value) || value < minimum || (maximum !== undefined && value > maximum)) {
    const range = maximum === undefined ? `at least ${minimum}` : `from ${minimum} through ${maximum}`;
    throw new Error(`${name} must be an integer ${range}`);
  }
}

export function prepareAgentRoomRequest(
  request: AgentRoomRequest,
  signal?: AbortSignal,
): { url: string; init: RequestInit } {
  const capability = capabilityUrl(request.url);

  switch (request.action) {
    case "observe": {
      const since = request.since ?? 0;
      const waitSeconds = request.waitSeconds ?? 0;
      validateInteger("since", since, 0);
      validateInteger("waitSeconds", waitSeconds, 0, 300);
      const wait = waitSeconds === 0 ? "" : `&wait=${waitSeconds}`;
      return {
        url: `${roomEndpoint(capability, "messages")}?since=${since}${wait}`,
        init: { method: "GET", signal },
      };
    }
    case "send":
      if (request.text === undefined) throw new Error("send requires text");
      return {
        url: roomEndpoint(capability, "messages"),
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: request.text }),
          signal,
        },
      };
    case "close":
      return {
        url: roomEndpoint(capability, "close"),
        init: { method: "POST", signal },
      };
  }
}

async function readResponse(response: Response): Promise<{ body: string; truncated: boolean }> {
  const body = await response.text();
  const truncation = truncateHead(body, {
    maxBytes: DEFAULT_MAX_BYTES,
    maxLines: DEFAULT_MAX_LINES,
  });
  return { body: truncation.content, truncated: truncation.truncated };
}

function makeResult(
  action: AgentRoomAction,
  response: Response,
  body: string,
  truncated = false,
): AgentRoomResult {
  return {
    action,
    status: response.status,
    statusText: response.statusText,
    ok: response.ok,
    body,
    truncated,
  };
}

function parseTranscript(body: string): Transcript {
  const parsed = JSON.parse(body) as Partial<Transcript>;
  if (!Array.isArray(parsed.messages) || typeof parsed.closed !== "boolean") {
    throw new Error("Agent-room transcript response has an unexpected shape");
  }
  return parsed as Transcript;
}

async function observeRoom(
  request: AgentRoomRequest,
  signal: AbortSignal | undefined,
  fetchImpl: Fetch,
): Promise<AgentRoomResult> {
  const since = request.since ?? 0;
  let instructions: string | undefined;

  if (since === 0) {
    const capability = capabilityUrl(request.url);
    const response = await fetchImpl(capability, {
      headers: { Accept: "text/markdown, application/json;q=0.9" },
      signal,
    });
    const read = await readResponse(response);
    if (!response.ok || read.truncated) return makeResult("observe", response, read.body, read.truncated);
    instructions = read.body;
  }

  const prepared = prepareAgentRoomRequest(request, signal);
  const response = await fetchImpl(prepared.url, prepared.init);
  const read = await readResponse(response);
  if (!response.ok || read.truncated) return makeResult("observe", response, read.body, read.truncated);

  const transcript = parseTranscript(read.body);
  const latest = transcript.messages.reduce((greatest, message) => Math.max(greatest, message.id), since);
  const status = transcript.closed ? "closed" : transcript.messages.length > 0 ? "updated" : "timeout";
  return makeResult("observe", response, JSON.stringify({
    ...(instructions === undefined ? {} : { instructions }),
    status,
    latest,
    closed: transcript.closed,
    messages: transcript.messages,
  }));
}

async function sendAndConfirm(
  request: AgentRoomRequest,
  signal: AbortSignal | undefined,
  fetchImpl: Fetch,
): Promise<AgentRoomResult> {
  const prepared = prepareAgentRoomRequest(request, signal);
  const response = await fetchImpl(prepared.url, prepared.init);
  const read = await readResponse(response);
  if (!response.ok || read.truncated) return makeResult("send", response, read.body, read.truncated);

  const created = JSON.parse(read.body) as { id?: unknown };
  if (!Number.isInteger(created.id)) {
    return makeResult("send", response, JSON.stringify({
      id: null,
      confirmed: false,
      error: "creation response did not contain an integer message ID",
    }));
  }
  const id = created.id as number;
  const capability = capabilityUrl(request.url);
  const confirmationResponse = await fetchImpl(
    `${roomEndpoint(capability, "messages")}?since=${Math.max(0, id - 1)}`,
    { method: "GET", signal },
  );
  const confirmation = await readResponse(confirmationResponse);
  if (!confirmationResponse.ok || confirmation.truncated) {
    return makeResult("send", confirmationResponse, JSON.stringify({
      id,
      confirmed: false,
      error: confirmation.truncated
        ? "read-back response was truncated"
        : `read-back failed: HTTP ${confirmationResponse.status}`,
    }), confirmation.truncated);
  }

  const transcript = parseTranscript(confirmation.body);
  const confirmed = transcript.messages.some((message) => message.id === id);
  return makeResult("send", response, JSON.stringify({ id, confirmed }));
}

export async function requestAgentRoom(
  request: AgentRoomRequest,
  signal?: AbortSignal,
  fetchImpl: Fetch = fetch,
): Promise<AgentRoomResult> {
  if (request.action === "observe") return observeRoom(request, signal, fetchImpl);
  if (request.action === "send") return sendAndConfirm(request, signal, fetchImpl);

  const prepared = prepareAgentRoomRequest(request, signal);
  const response = await fetchImpl(prepared.url, prepared.init);
  const read = await readResponse(response);
  return makeResult("close", response, read.body, read.truncated);
}

function formatResult(result: AgentRoomResult): string {
  const status = `HTTP ${result.status}${result.statusText ? ` ${result.statusText}` : ""}`;
  const truncation = result.truncated ? "\n[Response truncated; continue from the greatest message ID shown.]" : "";
  return result.body ? `${status}\n${result.body}${truncation}` : `${status}${truncation}`;
}

export default function agentRoom(pi: ExtensionAPI) {
  pi.registerTool({
    name: "agent_room",
    label: "Agent Room",
    description:
      "Observe, send to, or close a two-agent room using its exact capability URL. Observe includes room instructions only when since is zero, then returns incremental messages. Send confirms creation by reading the message back without returning the transcript. Use close only with explicit user authorization.",
    promptSnippet: "Observe or participate in a two-agent capability-URL room",
    promptGuidelines: [
      "Use agent_room instead of shell HTTP commands for agent-room capability URLs when this tool is available.",
      "Start with agent_room observe since 0, then continue from the greatest message ID returned.",
      "Use agent_room close only after the user explicitly authorizes closing the room.",
    ],
    parameters: Type.Object({
      url: Type.String({ description: "Exact agent-room capability URL supplied by the user" }),
      action: StringEnum(AGENT_ROOM_ACTIONS),
      text: Type.Optional(Type.String({ description: "Message text; required for send" })),
      since: Type.Optional(Type.Integer({
        minimum: 0,
        description: "Greatest message ID already observed; defaults to zero",
      })),
      waitSeconds: Type.Optional(Type.Integer({
        minimum: 0,
        maximum: 300,
        description: "Observe long-poll duration; zero performs an immediate read",
      })),
    }),
    async execute(_toolCallId, params, signal) {
      const result = await requestAgentRoom(params, signal);
      return {
        content: [{ type: "text", text: formatResult(result) }],
        details: result,
      };
    },
  });
}
