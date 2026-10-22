import { afterEach, describe, expect, test } from "bun:test";
import { LinkMessaging, type LinkDelivery, type LinkMessagingOptions, type LinkOutcome, type LinkPeer, type LinkResult } from "../../tools/pi-link/messaging";

// This is a transport contract test, not proof of Pi inbox or WebSocket integration.
// The bus uses only the public module methods; roster/socket authority remains here.
class Bus {
  nodes = new Map<string, Node>();
  extra: LinkPeer[] = [];
  failed = new Set<string>();
  dropReceipts = false;
  dropWorkers = false;
  beforeDelivery?: () => void;
  add(id: string, name: string, options: Partial<LinkMessagingOptions> = {}): Node {
    const node = new Node(this, id, name, options);
    this.nodes.set(id, node);
    return node;
  }
  peers(): LinkPeer[] {
    return [...this.nodes.values()].filter(n => n.connected).map(n => ({ name: n.name, sessionId: n.id, messagingVersion: n.version })).concat(this.extra);
  }
  hub(): Node { return this.nodes.get("hub")!; }
  dispose(): void { for (const n of this.nodes.values()) n.link.disconnect(); }
}
class Node {
  link: LinkMessaging;
  inbox: LinkDelivery[] = [];
  admitted: LinkDelivery[] = [];
  sent: unknown[] = [];
  connected = true;
  version: number | undefined = 2;
  hubSupported = true;
  enqueueFails = false;
  constructor(readonly bus: Bus, readonly id: string, public name: string, options: Partial<LinkMessagingOptions>) {
    this.link = new LinkMessaging({
      self: () => ({ name: this.name, sessionId: this.id }),
      role: () => !this.connected ? "disconnected" : this.id === "hub" ? "hub" : "client",
      peers: () => bus.peers(),
      hubSupported: () => this.hubSupported,
      testDeadlineMs: 40,
      sendHub: frame => {
        this.sent.push(structuredClone(frame));
        if (!this.connected) return false;
        bus.hub().link.handleHub(structuredClone(frame), { name: this.name, sessionId: this.id });
        return true;
      },
      sendPeer: (peer, frame) => {
        const target = bus.nodes.get(peer.sessionId);
        if (!target?.connected || bus.failed.has(peer.sessionId)) return false;
        const type = (frame as any).type;
        if (type === "link_receipt" && bus.dropReceipts) return true;
        if (type === "link_workers" && bus.dropWorkers) return true;
        if (type === "link_delivery") bus.beforeDelivery?.();
        target.link.handleIncoming(structuredClone(frame));
        return true;
      },
      deliverRoot: message => {
        if (this.enqueueFails) throw new Error("enqueue failed");
        this.inbox.push(message);
      },
      ...options,
    });
  }
  admit(): void {
    for (const message of this.inbox.splice(0)) {
      this.admitted.push(message);
      this.link.recordDelivered(message);
    }
  }
}
function outcomes(result: LinkResult): LinkOutcome[] { return result.details.outcomes as LinkOutcome[]; }
const buses: Bus[] = [];
function setup(): Bus { const bus = new Bus(); buses.push(bus); bus.add("hub", "hub@project"); return bus; }
afterEach(() => { for (const bus of buses.splice(0)) bus.dispose(); });

describe("root broadcast routing", () => {
  test("selects first-@ group once, excludes sender, preserves one ID and broadcast marker", async () => {
    const bus = setup();
    bus.hub().name = "coordinator@project@nested";
    const sender = bus.add("a", "a@project@nested");
    const b = bus.add("b", "b@project@nested");
    const unrelated = bus.add("c", "c@project");
    let late: Node | undefined;
    bus.beforeDelivery = () => {
      bus.beforeDelivery = undefined;
      late = bus.add("late", "late@project@nested");
      b.name = "renamed@other";
    };
    const result = await sender.link.broadcast({ message: "correction", replyTo: "correlation-not-target" });
    // Membership changes do not retract a selected copy. The late joiner has
    // the same group but was absent from the selection and receives no replay.
    expect(outcomes(result).map(o => [o.sessionId, o.status])).toEqual([["hub", "submitted"], ["b", "submitted"]]);
    expect(b.inbox[0]).toMatchObject({ id: result.details.messageId, broadcast: true });
    expect(sender.inbox).toEqual([]);
    expect(unrelated.inbox).toEqual([]);
    expect(late!.inbox).toEqual([]);
    expect(bus.hub().inbox[0]).toMatchObject({ id: result.details.messageId, broadcast: true, from: sender.name, fromSessionId: "a", replyTo: "correlation-not-target" });
  });
  for (const senderId of ["hub", "a"]) for (const replyTo of [undefined, "", "correlation-not-target"]) {
    test(`${senderId} broadcast accepts ${replyTo === undefined ? "omitted" : JSON.stringify(replyTo)} correlation`, async () => {
      const bus = new Bus(); buses.push(bus);
      const workerMessages: LinkDelivery[] = [];
      const worker = { workerId: "owned-worker", taskName: "task" };
      const integration: Partial<LinkMessagingOptions> = { workers: {
        broadcast: async message => { workerMessages.push(message); return [{ ...worker, status: "submitted" }]; },
        reply: async () => ({ status: "failed" }),
      } };
      const hub = bus.add("hub", "hub@project", senderId === "a" ? integration : {});
      const client = bus.add("a", "a@project", senderId === "hub" ? integration : {});
      const recipient = senderId === "hub" ? client : hub;
      // A genuine correlation remains correlation, not a recipient selector.
      const result = await bus.nodes.get(senderId)!.link.broadcast({ message: "correction", replyTo, includeSubagents: true });
      expect(outcomes(result).find(o => o.kind === "root")).toMatchObject({ sessionId: recipient.id, status: "submitted" });
      expect(outcomes(result).find(o => o.kind === "worker")).toMatchObject({ ...worker, status: "submitted" });
      expect(recipient.inbox).toHaveLength(1);
      expect(workerMessages).toHaveLength(1);
      for (const message of [recipient.inbox[0], workerMessages[0]]) {
        expect(message.id).toBe(result.details.messageId);
        expect(message.replyTo).toBe(replyTo || undefined);
      }
    });
  }
  test("all copies share the message ID, without requiring model-visible admission", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); const b = bus.add("b", "b@project");
    const result = await a.link.broadcast({ message: "stop" });
    expect(outcomes(result).every(o => o.status === "submitted")).toBe(true);
    expect([bus.hub().inbox[0].id, b.inbox[0].id]).toEqual([result.details.messageId, result.details.messageId]);
    expect(b.inbox[0].broadcast).toBe(true);
    const premature = await b.link.reply({ message: "question", replyTo: b.inbox[0].id });
    expect(outcomes(premature)[0].reason).toBe("unknown_reference");
  });
  test("plain names form the empty group; empty selection is explicit", async () => {
    const bus = setup(); const a = bus.add("a", "alpha"); const b = bus.add("b", "beta");
    expect(outcomes(await a.link.broadcast({ message: "plain" })).map(o => o.sessionId)).toEqual(["b"]);
    expect(b.inbox).toHaveLength(1);
    b.connected = false;
    const empty = await a.link.broadcast({ message: "alone" });
    expect(empty.details.empty).toBe(true); expect(outcomes(empty)).toEqual([]);
    expect(empty.content[0].text).toContain("empty selection");
    expect(empty.details.error).toBeUndefined();
    expect(empty.isError).toBeUndefined();
  });
  test("partial transport failures, old peers and missing IDs do not suppress healthy copies", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.add("b", "b@project");
    const old = bus.add("old", "old@project"); old.version = undefined;
    bus.extra.push({ name: "no-id@project", messagingVersion: 2 }); bus.failed.add("b");
    const result = await a.link.broadcast({ message: "fix" });
    expect(outcomes(result).map(o => [o.name, o.status, o.reason])).toEqual([
      ["hub@project", "submitted", undefined], ["b@project", "failed", "root_send_failed"],
      ["old@project", "unsupported", "peer_unsupported"], ["no-id@project", "unsupported", "missing_session_id"],
    ]);
    expect(bus.hub().inbox).toHaveLength(1);
    const text = result.content[0].text;
    expect(text).toContain("root hub@project (session hub): submitted");
    expect(text).toContain("root b@project (session b): failed (root_send_failed)");
    expect(text).toContain("root old@project (session old): unsupported (peer_unsupported)");
    expect(text).toContain("root no-id@project (session unavailable): unsupported (missing_session_id)");
    expect(result.details.error).toBeUndefined();
    expect(result.isError).toBeUndefined();
  });
  test("authoritative socket identity overrides forged author and worker attribution", async () => {
    const bus = setup(); const a = bus.add("a", "actual@project");
    expect(bus.hub().link.handleHub({ type: "link_request", messagingVersion: 2, id: "wire-id", operation: "broadcast", message: "hello", from: "forged", fromSessionId: "hub", fromWorker: { ownerSessionId: "hub", taskName: "fake" } }, { name: a.name, sessionId: a.id })).toBe(true);
    await Promise.resolve();
    expect(bus.hub().inbox).toEqual([]); // Worker fields on broadcast are rejected.
    bus.hub().link.handleHub({ type: "link_request", messagingVersion: 2, id: "plain-wire", operation: "broadcast", message: "hello", from: "forged", fromSessionId: "hub" }, { name: a.name, sessionId: a.id });
    expect(bus.hub().inbox[0]).toMatchObject({ from: a.name, fromSessionId: "a" });
    expect(a.link.handleIncoming({ type: "chat" })).toBe(false);
  });
  test("runtime argument extras cannot replace generated message ID or operation", async () => {
    const bus = setup(); const a = bus.add("a", "a@project");
    const result = await a.link.broadcast({ message: "hello", id: "forged-id", operation: "reply" } as any);
    expect(result.details.operation).toBe("broadcast");
    expect(result.details.messageId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(bus.hub().inbox[0].id).toBe(result.details.messageId);
  });
  test("local hub enqueue failure is a known failure", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.hub().enqueueFails = true;
    expect(outcomes(await a.link.broadcast({ message: "fix" }))[0].status).toBe("failed");
  });
});

describe("delivered-reference reply permission", () => {
  test("direct chats and chained replies route by session through rename and name reuse", async () => {
    const bus = setup(); const a = bus.add("a", "original@project"); const b = bus.add("b", "b@project");
    // Parent legacy chat integration supplies an authoritative author session ID.
    b.link.recordDelivered({ from: a.name, fromSessionId: "a", id: "direct-id", content: "direct" });
    a.name = "renamed@project";
    const impostor = bus.add("impostor", "original@project");
    const first = await b.link.reply({ replyTo: "direct-id", message: "clarify" });
    expect(outcomes(first)).toEqual([{ kind: "root", name: "renamed@project", sessionId: "a", status: "submitted" }]);
    expect(impostor.inbox).toEqual([]);
    a.admit();
    const answer = await a.link.reply({ replyTo: first.details.messageId as string, message: "answer" });
    expect(b.inbox[0]).toMatchObject({ id: answer.details.messageId, replyTo: first.details.messageId, fromSessionId: "a", content: "answer" });
    b.admit();
    const third = await b.link.reply({ replyTo: answer.details.messageId as string, message: "thanks" });
    expect(outcomes(third)[0].sessionId).toBe("a");
    expect(first.details.messageId).not.toBe(answer.details.messageId);
  });
  test("minimal persisted references restore while malformed historical records confer no permission", async () => {
    const bus = setup(); const a = bus.add("a", "a@project");
    a.link.restoreDelivered([null, { id: "malformed", from: "hub@project", content: "" },
      { id: "valid", from: "hub@project", fromSessionId: "hub", content: "" }]);
    expect(outcomes(await a.link.reply({ replyTo: "malformed", message: "no" }))[0].reason).toBe("unknown_reference");
    expect(outcomes(await a.link.reply({ replyTo: "valid", message: "yes" }))[0].status).toBe("submitted");
  });
  test("broadcast reply is private to the author, not its audience", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); const b = bus.add("b", "b@project");
    const broadcast = await a.link.broadcast({ message: "correction" }); b.admit();
    await b.link.reply({ replyTo: broadcast.details.messageId as string, message: "clarification" });
    expect(a.inbox).toHaveLength(1); expect(bus.hub().inbox).toHaveLength(1);
    expect(a.inbox[0].broadcast).toBeUndefined();
  });
  test.each([
    ["offline", "offline"], ["group", "outside_group"], ["unsupported", "peer_unsupported"],
  ])("reply refuses %s original author without name fallback", async (change, reason) => {
    const bus = setup(); const a = bus.add("a", "old@project"); const b = bus.add("b", "b@project");
    b.link.recordDelivered({ from: a.name, fromSessionId: "a", id: "received", content: "hello" });
    if (change === "offline") a.connected = false;
    if (change === "group") a.name = "new@other";
    if (change === "unsupported") a.version = 0;
    const replacement = bus.add("replacement", "old@project");
    const result = await b.link.reply({ replyTo: "received", message: "reply" });
    expect(outcomes(result)[0].reason).toBe(reason); expect(replacement.inbox).toEqual([]);
  });
  test("unknown UUID never emits a request; disconnect retains references but reset revokes them", async () => {
    const bus = setup(); const a = bus.add("a", "a@project");
    const unknown = await a.link.reply({ replyTo: "guessed", message: "hello" });
    expect(outcomes(unknown)[0].reason).toBe("unknown_reference"); expect(a.sent).toEqual([]);
    expect(unknown.content[0].text).toContain("failed (unknown_reference)");
    expect(unknown.details.error).toBe("unknown_reference");
    expect(unknown.isError).toBe(true);
    a.link.recordDelivered({ from: bus.hub().name, fromSessionId: "hub", id: "received", content: "hello" });
    a.link.disconnect();
    expect(outcomes(await a.link.reply({ replyTo: "received", message: "reply" }))[0].status).toBe("submitted");
    a.link.reset();
    expect(outcomes(await a.link.reply({ replyTo: "received", message: "reply" }))[0].reason).toBe("unknown_reference");
  });
});

describe("bounded receipts and owner-only worker boundary", () => {
  test("unsupported hub is explicit and sends nothing", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); a.hubSupported = false;
    const result = await a.link.broadcast({ message: "hello" });
    expect(outcomes(result)[0]).toMatchObject({ status: "unsupported", reason: "hub_unsupported" });
    expect(result.details.error).toBe("hub_unsupported");
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("unsupported (hub_unsupported)");
    expect(a.sent).toEqual([]);
  });
  test("lost receipt is unknown, no retry, despite already accepted copies", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.dropReceipts = true;
    const result = await a.link.broadcast({ message: "only once" });
    expect(outcomes(result)[0]).toMatchObject({ status: "unknown", reason: "routing_deadline" });
    expect(result.content[0].text).toContain("Recipient selection and submission outcomes are unknown");
    expect(result.content[0].text).toContain("routing via hub: unknown (routing_deadline)");
    expect(result.details.error).toBe("routing_deadline");
    expect(result.isError).toBe(true);
    expect(a.sent).toHaveLength(1); expect(bus.hub().inbox).toHaveLength(1);
  });
  test("a reply with a lost receipt still names its single resolved destination", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.dropReceipts = true;
    a.link.recordDelivered({ id: "received", from: "hub@project", fromSessionId: "hub", content: "hello" });
    const result = await a.link.reply({ replyTo: "received", message: "reply" });
    expect(result.content[0].text).toContain("Reply destination: root hub@project (session hub)");
    expect(result.content[0].text).toContain("Submission outcome is unknown");
    expect(result.details.error).toBe("routing_deadline");
    expect(result.details.messageId).toBeString();
    expect(bus.hub().inbox[0].id).toBe(result.details.messageId);
  });
  test("disconnect resolves pending unknown; abort before send is skipped", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.dropReceipts = true;
    const pending = a.link.broadcast({ message: "hello" }); a.link.disconnect();
    expect(outcomes(await pending)[0]).toMatchObject({ status: "unknown", reason: "disconnected" });
    const abort = new AbortController(); abort.abort();
    expect(outcomes(await a.link.broadcast({ message: "never" }, abort.signal))[0].status).toBe("skipped");
    expect(a.sent).toHaveLength(1);
  });
  test("worker opt-in reports unsupported per owner, including sender, separately from root success", async () => {
    const bus = setup(); const a = bus.add("a", "a@project");
    const result = await a.link.broadcast({ message: "correction", includeSubagents: true });
    expect(outcomes(result).map(o => [o.kind, o.sessionId, o.status])).toEqual([
      ["root", "hub", "submitted"], ["workers", "hub", "unsupported"], ["workers", "a", "unsupported"],
    ]);
    expect(a.inbox).toEqual([]);
    expect(result.content[0].text).toContain("workers of a@project (owner session a): unsupported (worker_integration_unavailable)");
  });
  test("owner bridge reports worker partial outcomes without parent model delivery", async () => {
    const bus = setup();
    const received: LinkDelivery[] = [];
    const a = bus.add("a", "a@project", { workers: {
      broadcast: async message => { received.push(message); return [{ workerId: "active-id", taskName: "active", status: "submitted" }, { workerId: "finished-id", taskName: "finished-during-send", status: "skipped" }]; },
      reply: async () => ({ status: "unsupported" }),
    } });
    const result = await a.link.broadcast({ message: "correction", includeSubagents: true });
    expect(outcomes(result).filter(o => o.kind === "worker").map(o => [o.taskName, o.status])).toEqual([["active", "submitted"], ["finished-during-send", "skipped"]]);
    expect(received[0]).toMatchObject({ id: result.details.messageId, fromSessionId: "a", broadcast: true });
    expect(a.inbox).toEqual([]);
  });
  test("lost worker receipt retains independent submitted root outcomes", async () => {
    const bus = setup(); const a = bus.add("a", "a@project"); bus.dropWorkers = true;
    const result = await bus.hub().link.broadcast({ message: "fix", includeSubagents: true });
    expect(outcomes(result)).toContainEqual({ kind: "root", name: a.name, sessionId: "a", status: "submitted" });
    expect(outcomes(result)).toContainEqual({ kind: "workers", name: a.name, sessionId: "a", status: "unknown", reason: "worker_routing_deadline" });
    expect(a.inbox).toHaveLength(1);
  });
  test("worker-authored reference answers go only to its manager bridge destination", async () => {
    const bus = setup();
    const answers: Array<{ task: { workerId: string; taskName: string }; message: LinkDelivery }> = [];
    const owner = bus.add("owner", "owner@project", { workers: {
      broadcast: async () => [],
      reply: async (task, message) => { answers.push({ task, message }); return { status: "submitted" }; },
    } });
    // Only parent-authoritative delivered records may carry worker attribution.
    bus.hub().link.recordDelivered({ id: "worker-question", from: owner.name, fromSessionId: owner.id,
      fromWorker: { ownerSessionId: owner.id, taskName: "clarifier", workerId: "clarifier-id" }, content: "question" });
    const result = await bus.hub().link.reply({ replyTo: "worker-question", message: "answer" });
    expect(outcomes(result)).toEqual([{ kind: "worker", name: owner.name, sessionId: owner.id, taskName: "clarifier", workerId: "clarifier-id", status: "submitted" }]);
    expect(answers).toHaveLength(1); expect(answers[0].task).toEqual({ taskName: "clarifier", workerId: "clarifier-id" });
    expect(answers[0].message).toMatchObject({ id: result.details.messageId, replyTo: "worker-question", fromSessionId: "hub" });
    expect(result.content[0].text).toContain("worker clarifier (worker ID clarifier-id; owner owner@project, session owner): submitted");
    expect(owner.inbox).toEqual([]);
  });
  test("worker display-name reuse cannot replace the delivered stable worker ID", async () => {
    const bus = setup();
    const live = { workerId: "new-worker-id", taskName: "reused-task" };
    const attempted: string[] = [];
    const owner = bus.add("owner", "owner@project", { workers: {
      broadcast: async () => [],
      reply: async worker => {
        attempted.push(worker.workerId);
        return worker.workerId === live.workerId
          ? { status: "submitted" }
          : { status: "skipped", reason: "worker_unavailable" };
      },
    } });
    bus.hub().link.recordDelivered({ id: "old-worker-question", from: owner.name, fromSessionId: owner.id,
      fromWorker: { ownerSessionId: owner.id, taskName: live.taskName, workerId: "old-worker-id" }, content: "question" });
    const result = await bus.hub().link.reply({ replyTo: "old-worker-question", message: "answer" });
    expect(attempted).toEqual(["old-worker-id"]);
    expect(outcomes(result)[0]).toMatchObject({ workerId: "old-worker-id", taskName: live.taskName, status: "skipped", reason: "worker_unavailable" });
    expect(owner.inbox).toEqual([]);
  });
  test("name-only historical worker references confer no reply permission", async () => {
    const bus = setup(); const owner = bus.add("owner", "owner@project");
    bus.hub().link.recordDelivered({ id: "name-only", from: owner.name, fromSessionId: owner.id,
      fromWorker: { ownerSessionId: owner.id, taskName: "reused-task" }, content: "question" });
    const result = await bus.hub().link.reply({ replyTo: "name-only", message: "answer" });
    expect(outcomes(result)[0].reason).toBe("unknown_reference");
    expect(owner.inbox).toEqual([]);
  });
  test("absent worker reply bridge is unsupported, never delivered to the owner model", async () => {
    const bus = setup(); const owner = bus.add("owner", "owner@project");
    bus.hub().link.recordDelivered({ id: "worker-question", from: owner.name, fromSessionId: owner.id,
      fromWorker: { ownerSessionId: owner.id, taskName: "clarifier", workerId: "clarifier-id" }, content: "question" });
    const result = await bus.hub().link.reply({ replyTo: "worker-question", message: "answer" });
    expect(outcomes(result)[0]).toMatchObject({ kind: "worker", taskName: "clarifier", status: "unsupported", reason: "worker_integration_unavailable" });
    expect(owner.inbox).toEqual([]);
  });
  test("empty active-worker snapshot is not a disconnected outcome", async () => {
    const bus = setup(); const a = bus.add("a", "a@project", { workers: { broadcast: async () => [], reply: async () => ({ status: "skipped" }) } });
    const result = await bus.hub().link.broadcast({ message: "fix", includeSubagents: true });
    expect(outcomes(result).filter(o => o.sessionId === a.id)).toEqual([{ kind: "root", name: a.name, sessionId: a.id, status: "submitted" }]);
  });
});


describe("manager-authoritative worker replies", () => {
  test("child-only reference routes via hub preserving worker identity and private stable-ID answer", async () => {
    const bus = setup(); const author = bus.add("author", "author@project");
    const answers: any[] = [];
    const owner = bus.add("owner", "owner@project", { workers: {
      broadcast: async () => [], reply: async (worker, message) => { answers.push({ worker, message }); return { status: "submitted" }; },
    } });
    const reference = { from: author.name, fromSessionId: author.id, id: "child-only", content: "correction" };
    const worker = { workerId: "stable-child", taskName: "reused-display" };
    const question = await owner.link.replyFromWorker(worker, reference, "which case?");
    expect(outcomes(question)[0].status).toBe("submitted");
    expect(author.inbox[0].fromWorker).toEqual({ ...worker, ownerSessionId: owner.id });
    expect(bus.hub().inbox).toEqual([]); expect(owner.inbox).toEqual([]);
    author.admit();
    const answer = await author.link.reply({ replyTo: question.details.messageId as string, message: "only direct cases" });
    expect(outcomes(answer)[0]).toMatchObject({ workerId: worker.workerId, status: "submitted" });
    expect(answers[0].worker).toEqual(worker);
    expect(owner.inbox).toEqual([]);
  });
  test("dynamic integration absence stays unsupported rather than callback failure", async () => {
    const bus = setup(); let installed = false;
    const owner = bus.add("owner", "owner@project", { workers: () => installed ? { broadcast: async () => [], reply: async () => ({ status: "skipped" }) } : undefined });
    expect(outcomes(await bus.hub().link.broadcast({ message: "first", includeSubagents: true }))).toContainEqual({ kind: "workers", name: owner.name, sessionId: owner.id, status: "unsupported", reason: "worker_integration_unavailable" });
    installed = true;
    expect(outcomes(await bus.hub().link.broadcast({ message: "second", includeSubagents: true })).some(o => o.sessionId === owner.id && o.kind === "workers")).toBe(false);
  });
  test("wire worker attribution cannot claim another owner", async () => {
    const bus = setup(); const owner = bus.add("owner", "owner@project");
    bus.hub().link.handleHub({ type: "link_request", messagingVersion: 2, id: "forged-worker", operation: "reply", message: "fake", replyTo: "ref", destination: { name: "hub@project", sessionId: "hub" }, fromWorker: { workerId: "id", taskName: "name", ownerSessionId: "another" } }, { name: owner.name, sessionId: owner.id });
    await Promise.resolve(); expect(bus.hub().inbox).toEqual([]);
  });
});


test("v1 messaging peers cannot silently downgrade worker attribution to a root author", async () => {
  const bus = setup(); const old = bus.add("old", "old@project"); old.version = 1;
  const owner = bus.add("owner", "owner@project");
  const result = await owner.link.replyFromWorker({ workerId: "child", taskName: "child" },
    { from: old.name, fromSessionId: old.id, id: "old-ref", content: "old correction" }, "question");
  expect(outcomes(result)[0]).toMatchObject({ status: "unsupported", reason: "peer_unsupported" });
  expect(old.inbox).toEqual([]);
});
