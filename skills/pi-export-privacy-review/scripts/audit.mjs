#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { extname } from "node:path";

const ANSI = /\x1b\[[0-?]*[ -\/]*[@-~]/g;
const SESSION_ID = /\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b/gi;
const SESSION_FILE = /(?:\/[^\s"']+\/)?\d{4}-\d{2}-\d{2}T[^\s"']+\.jsonl/g;
const EMAIL = /\b([A-Z0-9._%+-]+)@([A-Z0-9.-]+\.[A-Z]{2,})\b/gi;
const PATH = /\/(?:home|Users|root|tmp|private\/tmp|var|etc)\/[A-Za-z0-9._~+@%:,=\/-]+/g;
const MAX_CANDIDATES = 100;

const SECRET_PATTERNS = [
  ["private-key", /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/g],
  ["github-token", /\b(?:gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g],
  ["openai-shaped-key", /\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b/g],
  ["aws-access-key", /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ["slack-token", /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g],
  ["bearer-header", /\bBearer\s+[A-Za-z0-9._~+\/-]{16,}={0,2}\b/gi],
  ["cookie-header", /\b(?:Cookie|Set-Cookie)\s*:\s*[^\r\n]{8,}/gi],
  [
    "secret-assignment",
    /\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password)\s*[=:]\s*["']?([^\s"'<>]{8,})/gi,
  ],
  [
    "signed-url",
    /https?:\/\/[^\s<>"']+[?&](?:X-Amz-Signature|Signature|sig|token|key)=[^\s<>&"']+/gi,
  ],
];

function usage(message) {
  if (message) console.error(message);
  console.error("usage: node audit.mjs <pi-export.html|pi-session.jsonl>");
  process.exitCode = 2;
}

function hash(value) {
  return createHash("sha256").update(value).digest("hex").slice(0, 12);
}

function addOccurrence(map, value, path) {
  const key = hash(value);
  const current = map.get(key) ?? { count: 0, paths: [] };
  current.count += 1;
  if (current.paths.length < 3) current.paths.push(path);
  map.set(key, current);
  return { key, current };
}

function bounded(items, limit = MAX_CANDIDATES) {
  return {
    total: items.length,
    items: items.slice(0, limit),
    omitted: Math.max(0, items.length - limit),
  };
}

function parseExport(file, source) {
  if (extname(file).toLowerCase() === ".jsonl") {
    const lines = source.split(/\r?\n/);
    const records = [];
    for (let index = 0; index < lines.length; index += 1) {
      if (!lines[index].trim()) continue;
      try {
        records.push(JSON.parse(lines[index]));
      } catch (error) {
        throw new Error(`invalid JSONL record at line ${index + 1}: ${error.message}`);
      }
    }
    return {
      format: "jsonl",
      data: {
        header: records.find((record) => record?.type === "session") ?? null,
        entries: records,
      },
      payloadLine: null,
      outerText: "",
      decodedBytes: Buffer.byteLength(source),
      records: records.length,
    };
  }

  const match = source.match(
    /<script\b[^>]*\bid=["']session-data["'][^>]*>([A-Za-z0-9+/=\r\n]+)<\/script>/i,
  );
  if (!match) throw new Error("script#session-data base64 payload not found");
  const payloadLine = source.slice(0, match.index).split("\n").length;
  const encoded = match[1].replace(/\s/g, "");
  if (encoded.length % 4 !== 0) throw new Error("session-data payload has invalid base64 length");
  let decoded;
  try {
    decoded = Buffer.from(encoded, "base64").toString("utf8");
  } catch (error) {
    throw new Error(`base64 decoding failed: ${error.message}`);
  }
  let data;
  try {
    data = JSON.parse(decoded);
  } catch (error) {
    throw new Error(`decoded session JSON is invalid: ${error.message}`);
  }
  return {
    format: "html",
    data,
    payloadLine,
    outerText: source.slice(0, match.index) + source.slice(match.index + match[0].length),
    decodedBytes: Buffer.byteLength(decoded),
    records: null,
  };
}

function scanStrings(root) {
  const signatures = [];
  const secretCandidates = [];
  const emails = new Map();
  const paths = new Map();
  const fieldCounts = new Map();

  function walk(value, path = "$") {
    if (Array.isArray(value)) {
      value.forEach((item, index) => walk(item, `${path}[${index}]`));
      return;
    }
    if (value && typeof value === "object") {
      for (const [key, item] of Object.entries(value)) {
        fieldCounts.set(key, (fieldCounts.get(key) ?? 0) + 1);
        if (/signature/i.test(key) && typeof item === "string") {
          signatures.push({ field: key, path: `${path}.${key}`, bytes: Buffer.byteLength(item), hash: hash(item) });
        }
        walk(item, `${path}.${key}`);
      }
      return;
    }
    if (typeof value !== "string") return;

    const text = value.replace(ANSI, "");
    for (const [family, pattern] of SECRET_PATTERNS) {
      pattern.lastIndex = 0;
      for (const match of text.matchAll(pattern)) {
        secretCandidates.push({ family, path, bytes: Buffer.byteLength(match[0]), hash: hash(match[0]) });
      }
    }
    for (const match of text.matchAll(EMAIL)) {
      const { key, current } = addOccurrence(emails, match[0], path);
      current.masked = `${match[1].slice(0, 2)}…@${match[2]}`;
      emails.set(key, current);
    }
    for (const match of text.matchAll(PATH)) {
      const { current } = addOccurrence(paths, match[0], path);
      current.class = match[0].startsWith("/home/") || match[0].startsWith("/Users/")
        ? "home-path"
        : "system-or-temporary-path";
    }
  }

  walk(root);
  const signatureKinds = {};
  for (const item of signatures) signatureKinds[item.field] = (signatureKinds[item.field] ?? 0) + 1;
  return {
    signatures: {
      count: signatures.length,
      unique: new Set(signatures.map((item) => item.hash)).size,
      kinds: signatureKinds,
      first: signatures.at(0) ?? null,
      last: signatures.at(-1) ?? null,
    },
    secretCandidates: bounded(secretCandidates),
    personalDataCandidates: {
      emails: bounded([...emails.values()]),
    },
    filesystemPaths: {
      distinct: paths.size,
      occurrences: [...paths.values()].reduce((sum, item) => sum + item.count, 0),
      examples: [...paths.values()].slice(0, 20),
    },
    fieldCounts,
  };
}

function contentText(message) {
  return (message?.content ?? []).map((part) => (typeof part?.text === "string" ? part.text : "")).join("\n");
}

function inventoryEntries(data) {
  const entries = Array.isArray(data.entries) ? data.entries : [];
  const types = {};
  const roles = {};
  const roleBytes = {};
  const toolCalls = {};
  const calls = new Map();
  const imports = [];
  const compactions = [];

  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    types[entry?.type ?? "unknown"] = (types[entry?.type ?? "unknown"] ?? 0) + 1;
    const role = entry?.message?.role;
    if (role) {
      roles[role] = (roles[role] ?? 0) + 1;
      roleBytes[role] = (roleBytes[role] ?? 0) + Buffer.byteLength(JSON.stringify(entry.message));
    }
    if (entry?.type === "compaction") {
      compactions.push({ entry: index, summaryBytes: Buffer.byteLength(entry.summary ?? entry.content ?? "") });
    }
    for (const part of entry?.message?.content ?? []) {
      if (part?.type !== "toolCall") continue;
      toolCalls[part.name] = (toolCalls[part.name] ?? 0) + 1;
      calls.set(part.id, { entry: index, name: part.name, arguments: part.arguments ?? {} });
    }
    if (role !== "toolResult") continue;
    const call = calls.get(entry.message.toolCallId);
    if (!call || !["search_sessions", "read_session"].includes(call.name)) continue;
    const text = contentText(entry.message);
    imports.push({
      callEntry: call.entry,
      resultEntry: index,
      operation: call.name,
      requestedSession: call.arguments.sessionId ?? call.arguments.sessionFile ?? null,
      resultBytes: Buffer.byteLength(text),
      resultHash: hash(text),
      error: Boolean(entry.message.isError),
      foundSessionIds: [...new Set([...text.matchAll(SESSION_ID)].map((match) => match[0]))],
      foundSessionFiles: [...new Set([...text.matchAll(SESSION_FILE)].map((match) => match[0]))],
    });
  }

  return { entries: entries.length, types, roles, roleBytes, toolCalls, imports, compactions };
}

function scanOuter(text) {
  const candidates = [];
  for (const [family, pattern] of SECRET_PATTERNS) {
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      candidates.push({
        family,
        line: text.slice(0, match.index).split("\n").length,
        bytes: Buffer.byteLength(match[0]),
        hash: hash(match[0]),
      });
    }
  }
  return candidates;
}

const file = process.argv[2];
if (!file || process.argv.length !== 3) {
  usage(file ? "expected exactly one export path" : "missing export path");
} else {
  try {
    const source = readFileSync(file, "utf8");
    const parsed = parseExport(file, source);
    const scanned = scanStrings(parsed.data);
    const entries = inventoryEntries(parsed.data);
    const fields = scanned.fieldCounts;
    console.log(JSON.stringify({
      input: {
        file,
        format: parsed.format,
        bytes: Buffer.byteLength(source),
        lines: source.split("\n").length,
        payloadLine: parsed.payloadLine,
        decodedBytes: parsed.decodedBytes,
        records: parsed.records,
      },
      header: parsed.data.header ?? null,
      entries,
      embeddedSurfaces: {
        systemPromptBytes: Buffer.byteLength(parsed.data.systemPrompt ?? ""),
        toolSchemaBytes: Buffer.byteLength(JSON.stringify(parsed.data.tools ?? [])),
        renderedToolsBytes: Buffer.byteLength(JSON.stringify(parsed.data.renderedTools ?? {})),
        renderedToolItems: Object.keys(parsed.data.renderedTools ?? {}).length,
        thinkingFields: fields.get("thinking") ?? 0,
        attachmentFields: (fields.get("attachments") ?? 0) + (fields.get("images") ?? 0),
      },
      signatures: scanned.signatures,
      candidates: {
        secrets: scanned.secretCandidates,
        outerSecrets: bounded(scanOuter(parsed.outerText)),
        personalData: scanned.personalDataCandidates,
      },
      filesystemPaths: scanned.filesystemPaths,
      checkedCredentialFamilies: SECRET_PATTERNS.map(([family]) => family),
      limitations: [
        "Candidates require contextual confirmation; pattern matches are not findings.",
        "Phone numbers, postal addresses, and legal identifiers require contextual inspection.",
        "Imported-session excerpts must be inspected in context; counts alone do not classify sensitivity.",
      ],
    }, null, 2));
  } catch (error) {
    console.error(`audit failed: ${error.message}`);
    process.exitCode = 1;
  }
}
