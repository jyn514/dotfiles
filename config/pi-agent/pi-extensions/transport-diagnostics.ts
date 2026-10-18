import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { Model, Provider, SimpleStreamOptions, TranscriptContext } from "@earendil-works/pi-ai";
import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { channel } from "node:diagnostics_channel";
import { lookup } from "node:dns/promises";
import { appendFile, mkdir } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { isIP } from "node:net";
import { connect } from "node:tls";
import { createIpv4Fetch } from "./transport/ipv4.mjs";

interface RequestInfo { origin: string; path: string; method: string }
interface SocketInfo {
  localAddress?: string; localPort?: number; remoteAddress?: string; remotePort?: number;
  bytesRead?: number; bytesWritten?: number;
  on?(event: string, listener: (...args: any[]) => void): unknown;
  off?(event: string, listener: (...args: any[]) => void): unknown;
}
interface Trace {
  start: number; startedAt: string; attemptId: string; origin: string; path: string; method: string;
  sessionId?: string;
  headersMs?: number; status?: number; requestId?: string;
  requestHeaders?: Record<string, string>; responseHeaders?: Record<string, string>;
  cfRay?: string; lastChunkAt?: number; firstChunkMs?: number;
  chunkCount: number; receivedBodyBytes: number; maxChunkGapMs: number;
  lastEventType?: string; terminalEventType?: string; responseId?: string;
  socketId?: string; observedRequestsOnSocket?: number;
  attempt?: number;
  loopMaxDelayMs: number; loopLastGapMaxDelayMs: number; loopStalls: number; loopStalledMs: number;
  loopStart: ReturnType<typeof performance.eventLoopUtilization>;
  operation?: Operation;
  socket?: SocketInfo; peer?: SocketInfo;
}

interface Operation {
  id: string; attempts: number;
  model: string; provider: string; signal?: AbortSignal;
  current?: Trace; records: Array<Record<string, unknown>>;
}
const operations = new AsyncLocalStorage<Operation>();
const LOOP_INTERVAL_MS = 20;
const LOOP_STALL_MS = 100;
const TCP_INTERVAL_MS = 1000;

/** Parse only numeric kernel metadata, never retain ss's raw output. */
export function parseTcpSamples(output: string) {
  return output.trim().split("\n").filter(Boolean).flatMap(line => {
    const fields = line.trim().split(/\s+/);
    if (fields.length < 5) return [];
    if (!["ESTAB", "SYN-SENT", "SYN-RECV", "FIN-WAIT-1", "FIN-WAIT-2", "TIME-WAIT",
      "CLOSE-WAIT", "LAST-ACK", "CLOSING", "CLOSED"].includes(fields[0])) return [];
    if (!/^\d+$/.test(fields[1]) || !/^\d+$/.test(fields[2])) return [];
    const endpoint = (value: string) => {
      const match = /^(?:\[([^\]]+)\]|(.+)):(\d+)$/.exec(value);
      return match ? { address: match[1] ?? match[2], port: Number(match[3]) } : undefined;
    };
    const local = endpoint(fields[3]);
    const remote = endpoint(fields[4]);
    if (!local || !remote || !isIP(local.address) || !isIP(remote.address)) return [];
    const stats: Record<string, number | number[]> = {};
    for (const field of fields.slice(5)) {
      const match = /^(rtt|rto|cwnd|retrans|bytes_retrans|bytes_acked|bytes_received|unacked|lost|reordering|backoff|lastsnd|lastrcv|lastack|segs_in|segs_out):([\d.]+(?:\/[\d.]+)*)$/.exec(field);
      if (!match) continue;
      const values = match[2].split("/").map(Number);
      if (!values.every(Number.isFinite)) continue;
      stats[match[1]] = values.length === 1 ? values[0] : values;
    }
    return [{ state: fields[0], recvQueue: Number(fields[1]), sendQueue: Number(fields[2]), local, remote, stats }];
  });
}

function providerEvent(operation: Operation, data: unknown) {
  const trace = operation.current;
  if (!trace || !data || typeof data !== "object") return;
  const event = data as { type?: unknown; response?: { id?: unknown }; payload?: unknown };
  if (typeof event.type !== "string") return;
  // Use Pi's parsed event metadata, never inspect or retain SSE payload content.
  trace.lastEventType = event.type;
  if (["response.done", "response.completed", "response.incomplete", "response.failed"].includes(event.type)) {
    trace.terminalEventType = event.type;
  }
  const payload = (event.payload ?? event) as { response?: { id?: unknown } };
  if (typeof payload?.response?.id === "string") trace.responseId = payload.response.id;
}

/** Decorate the resolved provider, retaining its auth, catalog, parser, and options. */
export function instrumentProvider(provider: Provider, write: (record: object) => void, forcedFetch?: typeof fetch): Provider {
  function run(original: Provider["streamSimple"], model: Model<any>, context: TranscriptContext, options?: SimpleStreamOptions) {
    if (model.api !== "openai-codex-responses" || options?.transport === "websocket") {
      return original.call(provider, model, context, options);
    }
    const operation: Operation = { id: randomUUID(), attempts: 0,
      model: model.id, provider: provider.id, signal: options?.signal, records: [] };
    const fetcher = forcedFetch ?? options?.fetch ?? globalThis.fetch;
    const stream = original.call(provider, model, context, {
      ...options,
      fetch: ((input, init) => operations.run(operation, () => fetcher(input, init))) as typeof fetch,
      onProviderStreamEvent: async (event: unknown, eventModel: Model<any>) => {
        providerEvent(operation, event);
        await options?.onProviderStreamEvent?.(event, eventModel);
      },
    });
    // result() observes completion without consuming or replacing the event stream.
    void stream.result().then(message => {
      for (const record of operation.records) {
        const trace = record.trace as Trace;
        delete record.trace;
        const errors = record.errors as Array<{ name?: string }>;
        const cleanup = errors.length === 1 && errors[0].name === "AbortError"
          && !!trace.terminalEventType && !record.signalAborted;
        write({ ...record, model: operation.model, provider: operation.provider,
          lastEventType: trace.lastEventType ?? null, terminalEventType: trace.terminalEventType ?? null,
          responseId: trace.responseId ?? null,
          callStopReason: message.stopReason, transportOutcome: cleanup ? "reader_cleanup" : record.transportOutcome });
      }
    }).catch(() => {});
    return stream;
  }
  return { ...provider,
    stream: (model, context, options) => run(provider.stream, model, context, options),
    streamSimple: (model, context, options) => run(provider.streamSimple, model, context, options),
  } as Provider;
}

// Explicit allowlist: never persist authorization, cookies, account IDs, or arbitrary headers.
export function diagnosticHeaders(headers: string | Array<unknown>): Record<string, string> {
  const allowed = new Set(["user-agent", "originator", "openai-beta", "accept", "content-type",
    "content-length", "x-client-request-id", "x-request-id", "cf-ray", "server", "date"]);
  const pairs: Array<[string, string]> = [];
  if (typeof headers === "string") {
    for (const line of headers.split("\r\n")) {
      const colon = line.indexOf(":");
      if (colon > 0) pairs.push([line.slice(0, colon), line.slice(colon + 1).trim()]);
    }
  } else {
    for (let i = 0; i + 1 < headers.length; i += 2) pairs.push([String(headers[i]), String(headers[i + 1])]);
  }
  const result: Record<string, string> = {};
  for (const [name, value] of pairs) {
    const key = name.toLowerCase();
    if (allowed.has(key)) result[key] = value;
  }
  return result;
}

function socketInfo(socket?: SocketInfo): SocketInfo | undefined {
  if (!socket) return;
  const result: Record<string, string | number> = {};
  for (const key of ["localAddress", "localPort", "remoteAddress", "remotePort", "bytesRead", "bytesWritten"] as const) {
    const value = socket[key];
    if (typeof value === "string" || typeof value === "number") result[key] = value;
  }
  return result;
}

// Free-form messages and stacks can contain URLs or credentials. Keep typed codes only.
function errorCodes(error: unknown) {
  const result: Array<{ name?: string; code?: string }> = [];
  const seen = new Set();
  while (error && typeof error === "object" && !seen.has(error) && result.length < 8) {
    seen.add(error);
    const item = error as { name?: unknown; code?: unknown; cause?: unknown };
    const safe = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9_]+$/.test(value) ? value : undefined;
    result.push({ name: safe(item.name), code: safe(item.code) });
    error = item.cause;
  }
  return result;
}

/** Observe Node/Undici without changing dispatch, retries, or body consumption. */
export function observeTransport(write: (record: object) => void, session: () => string | undefined = () => undefined) {
  const traces = new WeakMap<object, Trace>();
  const sockets = new WeakMap<object, { id: string; requests: number }>();
  const active = new Set<Trace>();
  const socketListeners = new Set<() => void>();
  let loopTimer: ReturnType<typeof setInterval> | undefined;
  let tcpTimer: ReturnType<typeof setInterval> | undefined;
  let expectedTick = 0;
  let tcpDisabled = process.platform !== "linux";
  let stopped = false;
  let tcpChild: ReturnType<typeof execFile> | undefined;
  const subscriptions: Array<() => void> = [];
  const emit = (record: object) => { try { write(record); } catch {} };
  function sampleLoop(now = performance.now()) {
    if (!loopTimer) return;
    const delayMs = Math.max(0, now - expectedTick);
    if (now < expectedTick) return;
    expectedTick = now + LOOP_INTERVAL_MS;
    for (const trace of active) {
      trace.loopMaxDelayMs = Math.max(trace.loopMaxDelayMs, delayMs);
      trace.loopLastGapMaxDelayMs = Math.max(trace.loopLastGapMaxDelayMs, delayMs);
      if (delayMs >= LOOP_STALL_MS) { trace.loopStalls++; trace.loopStalledMs += delayMs; }
    }
  }
  function sampleTcp() {
    if (stopped || tcpDisabled || tcpChild || active.size === 0) return;
    const targets = [...active].filter(trace => trace.socket && trace.peer?.remoteAddress && trace.peer.localPort);
    if (targets.length === 0) return;
    const start = performance.now();
    const startedAt = new Date().toISOString();
    // Numeric destination-port filter avoids scanning unrelated TCP traffic.
    const ports = [...new Set(targets.map(trace => trace.peer!.remotePort!))];
    const filter = ports.flatMap((port, index) => [...(index ? ["or"] : []), "dport", "=", `:${port}`]);
    tcpChild = execFile("ss", ["-tinHO", "state", "connected", "(", ...filter, ")"],
      { timeout: 1000, maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
        tcpChild = undefined;
        if (stopped) return;
        if (error || stderr.trim()) {
          tcpDisabled = true;
          emit({ type: "tcp_sampling_status", timestamp: new Date().toISOString(), pid: process.pid,
            status: "disabled", reason: error?.code === "ENOENT" ? "ss_missing"
              : /Permission denied|Operation not permitted/.test(stderr) ? "permission_denied" : "ss_failed",
            errors: errorCodes(error), exitCode: typeof error?.code === "number" ? error.code : undefined });
          return;
        }
        for (const sample of parseTcpSamples(stdout)) {
          for (const trace of targets) {
            const peer = trace.peer!;
            const sameAddress = (a?: string, b?: string) => a?.replace(/^::ffff:/, "") === b?.replace(/^::ffff:/, "");
            if (sample.local.port !== peer.localPort || sample.remote.port !== peer.remotePort
                || !sameAddress(sample.local.address, peer.localAddress)
                || !sameAddress(sample.remote.address, peer.remoteAddress)) continue;
            emit({ type: "tcp_sample", timestamp: new Date().toISOString(), sampleStartedAt: startedAt,
              samplingMs: performance.now() - start, pid: process.pid, sessionId: trace.sessionId,
              attemptId: trace.attemptId, socketId: trace.socketId, ...sample });
          }
        }
      });
  }
  function startTimers() {
    if (loopTimer) return;
    expectedTick = performance.now() + LOOP_INTERVAL_MS;
    loopTimer = setInterval(sampleLoop, LOOP_INTERVAL_MS);
    loopTimer.unref();
    tcpTimer = setInterval(sampleTcp, TCP_INTERVAL_MS);
    tcpTimer.unref();
  }
  function stopTimers() {
    clearInterval(loopTimer); clearInterval(tcpTimer);
    loopTimer = undefined; tcpTimer = undefined;
  }
  function subscribe(name: string, handler: (event: any) => void) {
    const source = channel(name);
    // Diagnostics subscribers run inside the transport and must never throw.
    const listener = (event: unknown) => { try { handler(event); } catch {} };
    source.subscribe(listener);
    subscriptions.push(() => source.unsubscribe(listener));
  }
  subscribe("undici:request:create", ({ request }: { request: RequestInfo }) => {
    const url = new URL(request.path, request.origin);
    if (!/^\/(?:backend-api\/)?codex\/responses$/.test(url.pathname)) return;
    const operation = operations.getStore();
    const trace: Trace = { start: performance.now(), startedAt: new Date().toISOString(), attemptId: randomUUID(),
      sessionId: session(),
      origin: url.origin, path: url.pathname, method: request.method,
      chunkCount: 0, receivedBodyBytes: 0, maxChunkGapMs: 0,
      loopMaxDelayMs: 0, loopLastGapMaxDelayMs: 0, loopStalls: 0, loopStalledMs: 0,
      loopStart: performance.eventLoopUtilization(), operation };
    traces.set(request, trace);
    sampleLoop(); active.add(trace); startTimers();
    if (operation) { trace.attempt = ++operation.attempts; operation.current = trace; }
  });
  subscribe("undici:client:sendHeaders", ({ request, socket, headers }) => {
    const trace = traces.get(request);
    if (trace) {
      if (typeof headers === "string") trace.requestHeaders = diagnosticHeaders(headers);
      let state = sockets.get(socket);
      if (!state) {
        state = { id: randomUUID(), requests: 0 };
        sockets.set(socket, state);
        const id = state.id;
        const peer = socketInfo(socket);
        const event = (name: string, detail: object = {}) => emit({ type: "socket_event",
          timestamp: new Date().toISOString(), pid: process.pid, socketId: id, event: name,
          socket: { ...peer, ...socketInfo(socket) }, ...detail });
        const onEnd = () => event("end");
        const onError = (error: unknown) => event("error", { errors: errorCodes(error) });
        const onClose = (hadError: boolean) => { event("close", { hadError }); detach(); };
        const detach = () => {
          socket.off?.("end", onEnd); socket.off?.("error", onError); socket.off?.("close", onClose);
          socketListeners.delete(detach);
        };
        socket.on?.("end", onEnd); socket.on?.("error", onError); socket.on?.("close", onClose);
        socketListeners.add(detach);
      }
      state.requests++;
      sockets.set(socket, state);
      trace.socketId = state.id; trace.observedRequestsOnSocket = state.requests;
      trace.socket = socket; trace.peer = socketInfo(socket);
    }
  });
  subscribe("undici:request:headers", ({ request, response }) => {
    const trace = traces.get(request);
    if (!trace) return;
    trace.headersMs = performance.now() - trace.start;
    trace.status = response.statusCode;
    trace.responseHeaders = diagnosticHeaders(response.headers);
    for (let i = 0; i < response.headers.length; i += 2) {
      if (String(response.headers[i]).toLowerCase() === "x-request-id") {
        trace.requestId = String(response.headers[i + 1]);
      }
      if (String(response.headers[i]).toLowerCase() === "cf-ray") trace.cfRay = String(response.headers[i + 1]);
    }
  });
  subscribe("undici:request:bodyChunkReceived", ({ request, chunk }) => {
    const trace = traces.get(request);
    if (!trace) return;
    const now = performance.now();
    sampleLoop(now);
    if (trace.lastChunkAt !== undefined) trace.maxChunkGapMs = Math.max(trace.maxChunkGapMs, now - trace.lastChunkAt);
    trace.firstChunkMs ??= now - trace.start;
    trace.lastChunkAt = now;
    trace.loopLastGapMaxDelayMs = 0;
    trace.chunkCount++;
    trace.receivedBodyBytes += chunk.byteLength;
  });
  function finish(request: object, error?: any) {
    const trace = traces.get(request);
    if (!trace) return;
    traces.delete(request);
    const now = performance.now();
    sampleLoop(now);
    active.delete(trace);
    if (active.size === 0) stopTimers();
    const socket = { ...trace.peer, ...socketInfo(trace.socket), ...socketInfo(error?.socket) };
    const record = { type: "http_attempt", timestamp: new Date().toISOString(), startedAt: trace.startedAt,
      attemptId: trace.attemptId, pid: process.pid, sessionId: trace.sessionId,
      operationId: trace.operation?.id, attempt: trace.attempt,
      origin: trace.origin, path: trace.path, method: trace.method,
      elapsedMs: now - trace.start, headersMs: trace.headersMs,
      lastChunkAgoMs: trace.lastChunkAt === undefined ? null : now - trace.lastChunkAt,
      firstChunkMs: trace.firstChunkMs ?? null, maxChunkGapMs: trace.maxChunkGapMs,
      chunkCount: trace.chunkCount, receivedBodyBytes: trace.receivedBodyBytes,
      status: trace.status, requestId: trace.requestId, cfRay: trace.cfRay,
      requestHeaders: trace.requestHeaders, responseHeaders: trace.responseHeaders,
      errors: errorCodes(error), transportOutcome: error ? "error" : "http_complete",
      signalAborted: trace.operation?.signal?.aborted ?? null,
      eventLoop: { intervalMs: LOOP_INTERVAL_MS, stallThresholdMs: LOOP_STALL_MS,
        maxDelayMs: trace.loopMaxDelayMs, lastChunkGapMaxDelayMs: trace.loopLastGapMaxDelayMs,
        stallCount: trace.loopStalls, stalledMs: trace.loopStalledMs,
        utilization: performance.eventLoopUtilization(trace.loopStart) },
      socketId: trace.socketId, observedRequestsOnSocket: trace.observedRequestsOnSocket,
      addressFamily: socket.remoteAddress ? isIP(socket.remoteAddress) : null, socket };
    if (trace.operation) trace.operation.records.push({ ...record, trace });
    else emit(record);
  }
  subscribe("undici:request:trailers", ({ request }) => { finish(request); });
  subscribe("undici:request:error", ({ request, error }) => { finish(request, error); });
  return () => {
    stopped = true;
    stopTimers(); tcpChild?.kill();
    for (const unsubscribe of subscriptions) unsubscribe();
    for (const detach of socketListeners) detach();
    active.clear();
  };
}

/** TLS only: no HTTP request, OAuth token, or model invocation. */
export async function probeNetwork(hostname = "chatgpt.com", port = 443, timeoutMs = 10_000) {
  const start = performance.now();
  const addresses = await lookup(hostname, { all: true });
  const dnsMs = performance.now() - start;
  return Promise.all([4, 6].map(async family => {
    const address = addresses.find(candidate => candidate.family === family)?.address;
    if (!address) return { family, outcome: "no_address", dnsMs };
    return new Promise<object>(resolve => {
      const started = performance.now();
      let tcpMs: number | null = null;
      let finished = false;
      const socket = connect({ host: address, port, servername: isIP(hostname) ? undefined : hostname });
      const finish = (outcome: string, error?: unknown) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        resolve({ family, address, dnsMs, tcpMs, elapsedMs: performance.now() - started,
          outcome, errors: errorCodes(error) });
        socket.destroy();
      };
      const timer = setTimeout(() => finish("timeout"), timeoutMs);
      socket.once("connect", () => { tcpMs = performance.now() - started; });
      socket.once("secureConnect", () => finish("tls_connected"));
      socket.once("error", error => finish("error", error));
      socket.once("close", () => finish("closed"));
    });
  }));
}

export default function transportDiagnostics(pi: ExtensionAPI) {
  if (process.env.PI_TRANSPORT_DIAGNOSTICS !== "1" && process.env.PI_HTTP_FAMILY !== "4") return;
  const ipv4 = process.env.PI_HTTP_FAMILY === "4" ? createIpv4Fetch(process.argv[1]) : undefined;
  const directory = join(homedir(), ".pi", "agent", "logs");
  const file = join(directory, `transport-${process.pid}.jsonl`);
  let pending = Promise.resolve();
  let failed = false;
  let sessionId: string | undefined;
  const write = (record: object) => {
    pending = pending.then(async () => {
      if (failed) return;
      await mkdir(directory, { recursive: true, mode: 0o700 });
      await appendFile(file, JSON.stringify(record) + "\n", { mode: 0o600 });
    }).catch(() => {
      failed = true;
      process.stderr.write(`Pi transport diagnostics: cannot write ${file}\n`);
    });
  };
  const stop = observeTransport(write, () => sessionId);
  let original: Provider | undefined;
  pi.on("session_start", (_event, ctx) => {
    sessionId = ctx.sessionManager.getSessionId();
    if (original) return;
    original = ctx.modelRegistry.getProvider("openai-codex");
    if (original) pi.registerProvider(instrumentProvider(original, write, ipv4?.fetch as typeof fetch | undefined));
  });
  pi.registerCommand("transport-probe", {
    description: "Compare direct ChatGPT IPv4/IPv6 DNS, TCP, and TLS connectivity (no model request)",
    handler: async (_args, ctx) => {
      try {
        const results = await probeNetwork();
        write({ type: "network_probe", timestamp: new Date().toISOString(), pid: process.pid, sessionId, results });
        ctx.ui.notify(results.map(result => {
          const item = result as { family: number; outcome: string; dnsMs: number; tcpMs?: number | null; elapsedMs?: number };
          return `IPv${item.family}: ${item.outcome}; DNS ${item.dnsMs.toFixed(0)}ms`
            + (item.tcpMs == null ? "" : `; TCP ${item.tcpMs.toFixed(0)}ms`)
            + (item.elapsedMs === undefined ? "" : `; total ${item.elapsedMs.toFixed(0)}ms`);
        }).join("\n"), "info");
      } catch (error) {
        write({ type: "network_probe", timestamp: new Date().toISOString(), pid: process.pid, sessionId,
          outcome: "dns_error", errors: errorCodes(error) });
        ctx.ui.notify("ChatGPT DNS lookup failed; see transport log", "error");
      }
      await pending;
    },
  });
  pi.on("session_shutdown", async () => {
    stop();
    if (original) pi.registerProvider(original);
    await pending;
    await ipv4?.close();
  });
}
