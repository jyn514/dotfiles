import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  truncateHead,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";

export const AGENT_ROOM_ACTIONS = ["inspect", "read", "send", "wait", "close"] as const;
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

export function prepareAgentRoomRequest(
  request: AgentRoomRequest,
  signal?: AbortSignal,
): { url: string; init: RequestInit } {
  const capability = capabilityUrl(request.url);
  const headers = new Headers();
  let url = capability;
  let method = "GET";
  let body: string | undefined;

  switch (request.action) {
    case "inspect":
      headers.set("Accept", "text/markdown, application/json;q=0.9");
      break;
    case "read":
      url = `${roomEndpoint(capability, "messages")}?since=${request.since ?? 0}`;
      break;
    case "send":
      if (request.text === undefined) throw new Error("send requires text");
      url = roomEndpoint(capability, "messages");
      method = "POST";
      headers.set("Content-Type", "application/json");
      body = JSON.stringify({ text: request.text });
      break;
    case "wait": {
      if (request.since === undefined) throw new Error("wait requires since");
      const waitSeconds = request.waitSeconds ?? 180;
      if (!Number.isInteger(waitSeconds) || waitSeconds < 1 || waitSeconds > 300) {
        throw new Error("waitSeconds must be an integer from 1 through 300");
      }
      url = `${roomEndpoint(capability, "messages")}?since=${request.since}&wait=${waitSeconds}`;
      break;
    }
    case "close":
      url = roomEndpoint(capability, "close");
      method = "POST";
      break;
  }

  return { url, init: { method, headers, body, signal } };
}

export async function requestAgentRoom(
  request: AgentRoomRequest,
  signal?: AbortSignal,
  fetchImpl: Fetch = fetch,
): Promise<AgentRoomResult> {
  const prepared = prepareAgentRoomRequest(request, signal);
  const response = await fetchImpl(prepared.url, prepared.init);
  const body = await response.text();
  const truncation = truncateHead(body, {
    maxBytes: DEFAULT_MAX_BYTES,
    maxLines: DEFAULT_MAX_LINES,
  });

  return {
    action: request.action,
    status: response.status,
    statusText: response.statusText,
    ok: response.ok,
    body: truncation.content,
    truncated: truncation.truncated,
  };
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
      "Inspect, read, send, wait on, or close a two-agent room using its exact capability URL. The tool handles endpoint construction, JSON encoding, HTTP statuses, output truncation, and abortable long polling. Use close only with explicit user authorization.",
    promptSnippet: "Inspect or participate in a two-agent capability-URL room",
    promptGuidelines: [
      "Use agent_room instead of shell HTTP commands for agent-room capability URLs when this tool is available.",
      "Use agent_room close only after the user explicitly authorizes closing the room.",
    ],
    parameters: Type.Object({
      url: Type.String({ description: "Exact agent-room capability URL supplied by the user" }),
      action: StringEnum(AGENT_ROOM_ACTIONS),
      text: Type.Optional(Type.String({ description: "Message text; required for send" })),
      since: Type.Optional(Type.Integer({ minimum: 0, description: "Greatest message ID already observed" })),
      waitSeconds: Type.Optional(Type.Integer({
        minimum: 1,
        maximum: 300,
        description: "Long-poll duration for wait; defaults to 180 seconds",
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
