/** Optional, volatile commit-boundary integration. No transcript entries or disk receipts. */
export const CHECKPOINT_VERSION = 1;
export const CHECKPOINT_RESTORE_COMMAND = "subagent-checkpoint-restore";
export const CHECKPOINT_EXPORT_EVENT = "subagent:checkpoint:export";
export const CHECKPOINT_RESTORE_EVENT = "subagent:checkpoint:restore";
export const CHECKPOINT_NOTIFY = "__pi_subagent_checkpoint__:";

export type Checkpoint = { repository: string; commit: string; parent: string };
export type CheckpointEnvelope = { version: 1; checkpoint: Checkpoint | null };
/** The controller must apply synchronously, then set applied=true before emit returns. */
export type CheckpointRestore = CheckpointEnvelope & { applied: boolean };
/** Helper-to-manager notification; command completion alone does not acknowledge application. */
export type CheckpointRestoreResult = { version: 1; restored: boolean };
export function checkpointRestoreResult(value: unknown): CheckpointRestoreResult | undefined {
  if (!value || typeof value !== "object") return;
  const record = value as Record<string, unknown>;
  if (record.version === CHECKPOINT_VERSION && typeof record.restored === "boolean") {
    return { version: CHECKPOINT_VERSION, restored: record.restored };
  }
}

/** undefined means missing/malformed, distinct from an explicit retirement (null). */
export function checkpointEnvelope(value: unknown): CheckpointEnvelope | undefined {
  if (!value || typeof value !== "object") return;
  const envelope = value as Record<string, unknown>;
  if (envelope.version !== CHECKPOINT_VERSION || !("checkpoint" in envelope)) return;
  const checkpoint = envelope.checkpoint;
  if (checkpoint === null) return { version: CHECKPOINT_VERSION, checkpoint: null };
  if (!checkpoint || typeof checkpoint !== "object") return;
  const record = checkpoint as Record<string, unknown>;
  if (![record.repository, record.commit, record.parent].every(value => typeof value === "string" && value.length > 0)) return;
  return { version: CHECKPOINT_VERSION, checkpoint: {
    repository: record.repository as string, commit: record.commit as string, parent: record.parent as string,
  } };
}
