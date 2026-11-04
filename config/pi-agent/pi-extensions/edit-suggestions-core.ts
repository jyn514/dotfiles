// Execution-error diagnostics shared by native Pi and the guest tool worker.
import { constants } from "node:fs";
import { access, readFile, writeFile } from "node:fs/promises";
import type {
  createEditToolDefinition,
  generateDiffString,
  EditOperations,
  EditToolInput,
  EditToolOptions,
} from "@earendil-works/pi-coding-agent";

export interface EditSuggestionsSdk {
  createEditToolDefinition: typeof createEditToolDefinition;
  generateDiffString: typeof generateDiffString;
}

const localOperations: EditOperations = {
  access: (path) => access(path, constants.R_OK | constants.W_OK),
  readFile,
  writeFile: (path, content) => writeFile(path, content, "utf8"),
};

/**
 * Delegate all execution to Pi, enriching only recognized match failures.
 * Operations and context options pass through; compose this factory with existing
 * edit overrides instead of registering competing definitions. Render slots are
 * omitted so Pi retains its configured built-in previews and result renderer.
 */
export function createEditSuggestionsTool(sdk: EditSuggestionsSdk, cwd: string, options?: EditToolOptions): ReturnType<typeof createEditToolDefinition> {
  const { createEditToolDefinition, generateDiffString } = sdk;
  const { renderCall: _renderCall, renderResult: _renderResult, ...definition } = createEditToolDefinition(cwd, options);
  return {
    ...definition,
    async execute(id, input, signal, onUpdate, ctx) {
      // A per-call capture observes the exact read inside Pi's mutation queue;
      // a second read after failure could describe another writer's contents.
      let snapshot: Buffer | undefined;
      const operations = options?.operations ?? localOperations;
      const delegate = createEditToolDefinition(cwd, {
        ...options,
        operations: {
          ...operations,
          async readFile(path) {
            snapshot = await operations.readFile(path);
            return snapshot;
          },
        },
      });
      try {
        return await delegate.execute(id, input, signal, onUpdate, ctx);
      } catch (error) {
        if (!(error instanceof Error) || !snapshot || signal?.aborted) throw error;
        // Suggestions are best-effort diagnostics. A changed public diff format
        // must never replace a real tool failure with a formatter failure.
        let diagnostic: Error | undefined;
        try { diagnostic = enrichMatchError(error.message, snapshot.toString("utf8"), input, generateDiffString); }
        catch { /* Preserve the authoritative execution failure. */ }
        throw diagnostic ?? error;
      }
    },
  };
}

function enrichMatchError(message: string, rawContent: string, input: EditToolInput, diff: typeof generateDiffString): Error | undefined {
  // Pi currently exposes unstructured errors. Match the complete known error,
  // including count/path/index, and otherwise leave future errors untouched.
  const count = /^Found (\d+) occurrences of /.exec(message)?.[1];
  for (let i = 0; i < input.edits.length; i++) {
    const missing = input.edits.length === 1
      ? `Could not find the exact text in ${input.path}. The old text must match exactly including all whitespace and newlines.`
      : `Could not find edits[${i}] in ${input.path}. The oldText must match exactly including all whitespace and newlines.`;
    const duplicate = input.edits.length === 1
      ? `Found ${count} occurrences of the text in ${input.path}. The text must be unique. Please provide more context to make it unique.`
      : `Found ${count} occurrences of edits[${i}] in ${input.path}. Each oldText must be unique. Please provide more context to make it unique.`;
    if (message !== missing && (count === undefined || message !== duplicate)) continue;
    const oldText = normalizeToLF(input.edits[i].oldText);
    const content = normalizeToLF(rawContent.replace(/^\uFEFF/, ""));
    if (message === missing) {
      return getNotFoundError(input.path, i, input.edits.length, oldText, findClosestMatch(content, oldText), diff);
    }
    if (!oldText) return undefined;
    const summary = summarizeOccurrences(content, oldText);
    if (summary.count > 1 && String(summary.count) === count) {
      return getDuplicateError(input.path, i, input.edits.length, summary);
    }
  }
  return undefined;
}

function normalizeToLF(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

// Fork diagnostic policy; never used to select or execute a replacement.
function normalizeForFuzzyMatch(text: string): string {
  return (
    text
      .normalize("NFKC")
      // Strip trailing whitespace per line
      .split("\n")
      .map((line) => line.trimEnd())
      .join("\n")
      // Smart single quotes → '
      .replace(/[\u2018\u2019\u201A\u201B]/g, "'")
      // Smart double quotes → "
      .replace(/[\u201C\u201D\u201E\u201F]/g, '"')
      // Various dashes/hyphens → -
      // U+2010 hyphen, U+2011 non-breaking hyphen, U+2012 figure dash,
      // U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar, U+2212 minus
      .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, "-")
      // Special spaces → regular space
      // U+00A0 NBSP, U+2002-U+200A various spaces, U+202F narrow NBSP,
      // U+205F medium math space, U+3000 ideographic space
      .replace(/[\u00A0\u2002-\u200A\u202F\u205F\u3000]/g, " ")
  );
}

const MAX_ERROR_PREVIEW_LENGTH = 200;
const MAX_REPORTED_MATCH_LINES = 5;
const MAX_CLOSEST_MATCH_CONTENT_LENGTH = 1_000_000;
const MAX_CLOSEST_MATCH_OLD_TEXT_LENGTH = 4_000;
const MAX_CLOSEST_MATCH_ANCHORS = 100;
const MAX_CLOSEST_MATCH_DIFF_LINES = 12;
const MAX_CLOSEST_MATCH_DIFF_LINE_LENGTH = 200;

function formatTextPreview(text: string): string {
  const preview = text.length > MAX_ERROR_PREVIEW_LENGTH ? `${text.slice(0, MAX_ERROR_PREVIEW_LENGTH)}…` : text;
  return JSON.stringify(preview);
}

function diceSimilarity(left: string, right: string): number {
  if (left === right) return 1;
  if (left.length < 2 || right.length < 2) return 0;

  const leftBigrams = new Map<string, number>();
  for (let i = 0; i < left.length - 1; i++) {
    const bigram = left.slice(i, i + 2);
    leftBigrams.set(bigram, (leftBigrams.get(bigram) ?? 0) + 1);
  }

  let intersection = 0;
  for (let i = 0; i < right.length - 1; i++) {
    const bigram = right.slice(i, i + 2);
    const count = leftBigrams.get(bigram) ?? 0;
    if (count === 0) continue;
    intersection++;
    leftBigrams.set(bigram, count - 1);
  }

  return (2 * intersection) / (left.length + right.length - 2);
}

interface ClosestMatch {
  line: number;
  text: string;
}

function findClosestMatch(content: string, oldText: string): ClosestMatch | undefined {
  if (content.length > MAX_CLOSEST_MATCH_CONTENT_LENGTH || oldText.length > MAX_CLOSEST_MATCH_OLD_TEXT_LENGTH) {
    return undefined;
  }
  const normalizedContent = normalizeForFuzzyMatch(content);
  const normalizedOldText = normalizeForFuzzyMatch(oldText);
  if (normalizedOldText.length === 0) return undefined;

  const originalContentLines = content.split("\n");
  const contentLines = normalizedContent.split("\n");
  const oldTextLines = normalizedOldText.split("\n");
  if (oldTextLines.length > contentLines.length) return undefined;

  let anchorLineIndex = 0;
  for (let i = 1; i < oldTextLines.length; i++) {
    if (oldTextLines[i].length > oldTextLines[anchorLineIndex].length) anchorLineIndex = i;
  }
  const anchorText = oldTextLines[anchorLineIndex];
  if (anchorText.length === 0) return undefined;

  const rankedAnchors = contentLines
    .map((line, index) => ({ index, score: diceSimilarity(anchorText, line) }))
    .filter((candidate) => candidate.score >= 0.5)
    .sort((a, b) => b.score - a.score);
  const bestAnchorScore = rankedAnchors[0]?.score;
  if (bestAnchorScore === undefined) return undefined;
  const anchorCandidates = rankedAnchors.filter((candidate) => bestAnchorScore - candidate.score < 0.05);
  if (anchorCandidates.length > MAX_CLOSEST_MATCH_ANCHORS) return undefined;

  const candidates = new Map<number, { line: number; text: string; score: number }>();
  for (const anchor of anchorCandidates) {
    const startLineIndex = anchor.index - anchorLineIndex;
    if (startLineIndex < 0 || startLineIndex + oldTextLines.length > contentLines.length) continue;
    const normalizedText = contentLines.slice(startLineIndex, startLineIndex + oldTextLines.length).join("\n");
    const text = originalContentLines.slice(startLineIndex, startLineIndex + oldTextLines.length).join("\n");
    candidates.set(startLineIndex, {
      line: startLineIndex + 1,
      text,
      score: diceSimilarity(normalizedOldText, normalizedText),
    });
  }

  const ranked = [...candidates.values()].sort((a, b) => b.score - a.score);
  const best = ranked[0];
  if (!best || best.score < 0.8) return undefined;
  const secondBest = ranked[1];
  if (secondBest && best.score - secondBest.score < 0.05) return undefined;
  return { line: best.line, text: best.text };
}

interface ClosestMatchDiffLine {
  prefix: " " | "+" | "-";
  text: string;
}

function selectClosestMatchDiffLines(lines: ClosestMatchDiffLine[], contextLines: number): number[] {
  const selected = new Set<number>();
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].prefix === " ") continue;
    const start = Math.max(0, i - contextLines);
    const end = Math.min(lines.length, i + contextLines + 1);
    for (let j = start; j < end; j++) selected.add(j);
  }
  return [...selected].sort((a, b) => a - b);
}

function countRenderedClosestMatchDiffLines(indices: number[]): number {
  let count = indices.length;
  for (let i = 1; i < indices.length; i++) {
    if (indices[i] > indices[i - 1] + 1) count++;
  }
  return count;
}

function formatClosestMatchDiff(expected: string, found: string, generateDiffString: EditSuggestionsSdk["generateDiffString"]): string {
  // Reuse Pi's public diff algorithm, requesting all context before applying
  // the diagnostic-only line/width budget. Successful edit previews stay in Pi.
  const context = Math.max(expected.split("\n").length, found.split("\n").length);
  const rendered = generateDiffString(expected, found, context).diff;
  const diffLines: ClosestMatchDiffLine[] = rendered ? rendered.split("\n").map((line) => {
    // Public display format: sign, padded line number, space, original text.
    const match = /^([ +\-])\s*\d+ (.*)$/.exec(line);
    if (!match) throw new Error("Unsupported Pi display diff format");
    return { prefix: match[1] as ClosestMatchDiffLine["prefix"], text: match[2] };
  }) : [];

  let selectedIndices: number[] = [];
  for (let contextLines = 3; contextLines >= 0; contextLines--) {
    selectedIndices = selectClosestMatchDiffLines(diffLines, contextLines);
    if (countRenderedClosestMatchDiffLines(selectedIndices) <= MAX_CLOSEST_MATCH_DIFF_LINES) break;
  }
  if (countRenderedClosestMatchDiffLines(selectedIndices) > MAX_CLOSEST_MATCH_DIFF_LINES) {
    selectedIndices = selectedIndices.slice(0, MAX_CLOSEST_MATCH_DIFF_LINES - 1);
  }

  const output: string[] = [];
  let lastRenderedIndex: number | undefined;
  let renderedSelectionCount = 0;
  for (const index of selectedIndices) {
    const needsGap = lastRenderedIndex === undefined ? index > 0 : index > lastRenderedIndex + 1;
    const needsTrailingMarker = index < diffLines.length - 1 || renderedSelectionCount < selectedIndices.length - 1;
    const requiredLines = (needsGap ? 1 : 0) + 1 + (needsTrailingMarker ? 1 : 0);
    if (output.length + requiredLines > MAX_CLOSEST_MATCH_DIFF_LINES) break;
    if (needsGap) output.push("  …");
    const line = diffLines[index];
    const displayLine =
      line.text.length > MAX_CLOSEST_MATCH_DIFF_LINE_LENGTH
        ? `${line.text.slice(0, MAX_CLOSEST_MATCH_DIFF_LINE_LENGTH)}…`
        : line.text;
    output.push(`${line.prefix} ${displayLine}`);
    lastRenderedIndex = index;
    renderedSelectionCount++;
  }
  if (
    lastRenderedIndex !== undefined &&
    (lastRenderedIndex < diffLines.length - 1 || renderedSelectionCount < selectedIndices.length)
  ) {
    output.push("  …");
  }
  return output.join("\n");
}

interface OccurrenceSummary {
  count: number;
  lines: number[];
}

function summarizeOccurrences(content: string, oldText: string): OccurrenceSummary {
  const fuzzyContent = normalizeForFuzzyMatch(content);
  const fuzzyOldText = normalizeForFuzzyMatch(oldText);
  const matchContent = fuzzyOldText.length === 0 ? content : fuzzyContent;
  const matchText = fuzzyOldText.length === 0 ? oldText : fuzzyOldText;
  const lines: number[] = [];
  let count = 0;
  let line = 1;
  let scannedIndex = 0;
  let searchIndex = 0;

  while (true) {
    const matchIndex = matchContent.indexOf(matchText, searchIndex);
    if (matchIndex === -1) return { count, lines };
    for (let i = scannedIndex; i < matchIndex; i++) {
      if (matchContent[i] === "\n") line++;
    }
    count++;
    if (lines.length < MAX_REPORTED_MATCH_LINES) lines.push(line);
    scannedIndex = matchIndex;
    searchIndex = matchIndex + matchText.length;
  }
}

function getNotFoundError(
  path: string,
  editIndex: number,
  totalEdits: number,
  oldText: string,
  closestMatch: ClosestMatch | undefined,
  diff: typeof generateDiffString,
): Error {
  const target = totalEdits === 1 ? "oldText" : `edits[${editIndex}].oldText`;
  if (closestMatch) {
    return new Error(
      `Could not find ${target} in ${path}. Closest match starts at line ${closestMatch.line}:\n${formatClosestMatchDiff(oldText, closestMatch.text, diff)}`,
    );
  }
  return new Error(
    `Could not find ${target} in ${path}. Expected ${formatTextPreview(oldText)}. No exact or normalized match was found; check internal whitespace and newlines, or read the file again if it may have changed.`,
  );
}

function getDuplicateError(path: string, editIndex: number, totalEdits: number, summary: OccurrenceSummary): Error {
  const target = totalEdits === 1 ? "oldText" : `edits[${editIndex}].oldText`;
  const remainingCount = summary.count - summary.lines.length;
  const lineSummary = `${summary.lines.join(", ")}${remainingCount > 0 ? `, and ${remainingCount} more` : ""}`;
  return new Error(
    `Found ${summary.count} occurrences of ${target} in ${path}, starting at lines ${lineSummary}. Provide more surrounding context so the match is unique.`,
  );
}

