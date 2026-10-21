import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { queueGoalTurn, registerGoalCommand } from "./commands.ts";
import { createContinuationScheduler } from "./continuation-scheduler.ts";
import { assistantTurnTokensForToolCall, createGoalAccounting } from "./goal-accounting.ts";
import { createGoalPersistence } from "./goal-persistence.ts";
import {
  createGoalRuntimeEventHandlers,
  type GoalRuntimeEventHandlers,
} from "./goal-runtime-event-handlers.ts";
import { registerGoalRuntimeEvents } from "./goal-runtime-events.ts";
import { createGoalRuntimeState } from "./goal-runtime-state.ts";
import { createGoalRuntimeStatus, type StatusContext } from "./goal-runtime-status.ts";
import { createGoalStateController } from "./goal-state-controller.ts";
import { createProviderLimitAutoResumeScheduler } from "./provider-limit-auto-resume.ts";
import { createGoalRecoveryRuntime } from "./recovery-runtime.ts";
import {
  clearActiveHostOverflowRecovery,
  recoveryPhaseNeedsUserStartTurn,
  resetRecoveryMachine,
  setRecoveryPausedAttention,
} from "./recovery-machine.ts";
import { goalWithLiveUsage, updateGoalFromTool, updateGoalStatus, validateObjective } from "./state.ts";
import { registerGoalTools } from "./tools.ts";
import type { GoalToolStatus, GoalEntrySource, GoalResult, ThreadGoal } from "./types.ts";

export interface GoalRuntimeController extends GoalRuntimeEventHandlers {
  getGoalForDisplay(): ThreadGoal | null;
  needsHostOverflowUserReset(): boolean;
  setGoal(goal: ThreadGoal, source: GoalEntrySource, ctx: ExtensionContext): void;
  clearGoal(source: GoalEntrySource, ctx: ExtensionContext): void;
  editGoalObjective(goalId: string, objective: string, ctx: StatusContext): GoalResult;
  updateGoal(source: GoalEntrySource, ctx: ExtensionContext, toolCallId: string, status: GoalToolStatus, reason?: string, goalId?: string, signal?: AbortSignal): GoalResult;
  cancelProviderLimitAutoResume(goalId: string, ctx: StatusContext): void;
  resumeGoalWithContinuation(goalId: string, source: GoalEntrySource, ctx: StatusContext): GoalResult;
}

export function createGoalRuntimeController(pi: ExtensionAPI): GoalRuntimeController {
  const runtimeState = createGoalRuntimeState();
  const persistence = createGoalPersistence({ pi });

  const clearActiveAccounting = (): void => {
    runtimeState.accounting.activeGoalId = null;
    runtimeState.accounting.lastAccountedAt = null;
    runtimeState.accounting.lastSampledAt = null;
  };

  const resetErrorRecovery = (): void => {
    resetRecoveryMachine(runtimeState.recoveryState);
  };

  const goalForDisplay = () =>
    goalWithLiveUsage(
      persistence.getGoal(),
      runtimeState.accounting.activeGoalId,
      runtimeState.accounting.lastAccountedAt,
    );

  let autoResumeContext: ExtensionContext | null = null;
  const providerLimitAutoResume = createProviderLimitAutoResumeScheduler({
    onTimer(goalId) {
      if (!autoResumeContext || !autoResumeContext.isIdle() || autoResumeContext.hasPendingMessages()) {
        return false;
      }
      resumeGoalWithContinuation(goalId, "runtime", autoResumeContext);
      return true;
    },
  });

  const status = createGoalRuntimeStatus({
    getGoalForDisplay: goalForDisplay,
    getGoalStatus: () => persistence.getGoal()?.status ?? null,
    getRecoveryAttention: () => runtimeState.recoveryState.attention,
    isProviderLimitAutoResumeScheduled: providerLimitAutoResume.isScheduledFor,
  });

  const continuation = createContinuationScheduler({
    pi,
    getGoal: () => persistence.getGoal(),
    getRecoveryState: () => runtimeState.recoveryState,
    staleQueuedWorkGuard: runtimeState.staleQueuedWorkGuard,
    getCurrentTurnIndex: () => runtimeState.currentTurnIndex,
    getAgentRunSequence: () => runtimeState.agentRunSequence,
  });

  const stateController = createGoalStateController({
    pi,
    persistence,
    getRecoveryState: () => runtimeState.recoveryState,
    transitionEffectHandlers: {
      clearContinuation: continuation.clearContinuationState,
      clearActiveAccounting,
      resetRecovery: resetErrorRecovery,
      clearBudgetWarning: () => {
        runtimeState.accounting.budgetWarningSentFor = null;
      },
      clearHostOverflowRecovery: () => {
        clearActiveHostOverflowRecovery(runtimeState.recoveryState);
      },
      setRecoveryPausedAttention: (reason: string) => {
        setRecoveryPausedAttention(runtimeState.recoveryState, reason);
      },
      markContinuationQueued: continuation.markContinuationQueued,
      stopStatusRefresh: () => status.stopStatusRefresh(),
    },
    refreshUi: (ctx) => status.refreshUi(ctx),
  });

  const goalAccounting = createGoalAccounting({
    getGoal: () => stateController.getGoal(),
    getAccounting: () => runtimeState.accounting,
    applyRuntimeAccountingTransition(ctx, nextGoal) {
      stateController.applyGoalTransition({ kind: "runtime_accounting", nextGoal }, ctx);
    },
    sendMessage: pi.sendMessage.bind(pi),
  });

  const recoveryRuntime = createGoalRecoveryRuntime({
    getGoal: () => stateController.getGoal(),
    getRecoveryState: () => runtimeState.recoveryState,
    clearContinuationState: continuation.clearContinuationState,
    pauseGoalForRecovery(ctx, recoveryReason) {
      stateController.pauseForRecovery(ctx, recoveryReason);
    },
    refreshUi: status.refreshUi,
    maybeContinue: continuation.maybeContinue,
    scheduleProviderLimitAutoResume(goalId, ctx) {
      autoResumeContext = ctx;
      providerLimitAutoResume.schedule(goalId);
      status.refreshUi(ctx);
    },
  });

  const resumeGoalWithContinuation = (
    goalId: string,
    source: GoalEntrySource,
    ctx: StatusContext,
  ): GoalResult => {
    const current = stateController.getGoal();
    if ((current?.status === "blocked" || current?.status === "complete") && source !== "command") {
      return { ok: false, message: `Automatic recovery does not resume ${current.status} goals.`, goal: current };
    }
    const result = updateGoalStatus(current, "active");
    if (!result.ok || !result.goal || result.goal.goalId !== goalId) {
      return result;
    }
    providerLimitAutoResume.clear();
    if (current?.status === "blocked" || current?.status === "complete") {
      stateController.applyGoalTransition({ kind: "set", nextGoal: result.goal, source }, ctx);
    } else {
      stateController.resumePausedGoal(ctx);
    }
    const resumedGoal = stateController.getGoal();
    if (resumedGoal?.status === "active" && resumedGoal.goalId === goalId) {
      queueGoalTurn(pi, resumedGoal, "command_resume");
    }
    return result;
  };

  const eventHandlers = createGoalRuntimeEventHandlers({
    pi,
    runtimeState,
    stateController,
    continuation,
    goalAccounting,
    recoveryRuntime,
    status,
    providerLimitAutoResume,
    clearActiveAccounting,
    resetErrorRecovery,
    resumeGoalWithContinuation,
  });

  const updateGoal = (
    source: GoalEntrySource,
    ctx: ExtensionContext,
    toolCallId: string,
    status: GoalToolStatus,
    reason?: string,
    goalId?: string,
    signal?: AbortSignal,
  ): GoalResult => {
    const goal = stateController.getGoal();
    if (goal && runtimeState.completionGoalId !== null && runtimeState.completionGoalId !== goal.goalId) {
      return {
        ok: false,
        message: "Goal changed while this response was running; inspect the current goal before updating its status.",
        goal,
      };
    }
    if (signal?.aborted) {
      return { ok: false, message: "Goal update canceled; inspect the current goal before continuing.", goal };
    }
    const validation = updateGoalFromTool(goal, status, reason, goalId);
    if (!validation.ok) {
      return validation;
    }
    if (status === "paused") return stateController.updateGoal(source, ctx, status, reason);
    if (status === "active") {
      // Publish against current state without command resume's extra hidden turn.
      const result = stateController.updateGoal(source, ctx, status, reason, goalId);
      if (result.ok) {
        providerLimitAutoResume.clear();
        goalAccounting.beginAccounting(false);
      }
      return result;
    }
    providerLimitAutoResume.clear();
    if (status === "blocked") {
      continuation.clearPostCompactContinuationFallback();
    }
    const completedTurnTokens = assistantTurnTokensForToolCall(ctx.sessionManager.getBranch(), toolCallId);
    goalAccounting.accountProgress(ctx, false, completedTurnTokens, true);
    // A command can resume the goal before sibling tools finish and turn_end arrives.
    runtimeState.accounting.turnGoalId = null;
    return stateController.updateGoal(source, ctx, status, reason);
  };

  return {
    getGoalForDisplay: goalForDisplay,
    needsHostOverflowUserReset: () => recoveryPhaseNeedsUserStartTurn(runtimeState.recoveryState.phase),
    setGoal(nextGoal, source, ctx) {
      providerLimitAutoResume.clear();
      stateController.applyGoalTransition({ kind: "set", nextGoal, source }, ctx);
      // A tool-created goal is known to this response, unlike a concurrent /goal replacement.
      if (source === "tool") {
        runtimeState.completionGoalId = nextGoal.goalId;
      }
    },
    editGoalObjective(goalId, objective, ctx) {
      const current = stateController.getGoal();
      if (current?.goalId !== goalId) {
        return { ok: false, message: "Goal changed while editing; edit the current goal instead.", goal: current };
      }
      const error = validateObjective(objective);
      if (error) return { ok: false, message: error, goal: current };
      const changed = current.objective !== objective.trim();
      stateController.applyGoalTransition({ kind: "edit_objective", objective }, ctx);
      return {
        ok: true,
        message: changed ? "Goal objective updated." : "Goal unchanged.",
        goal: stateController.getGoal(),
      };
    },
    clearGoal(source, ctx) {
      providerLimitAutoResume.clear();
      stateController.applyGoalTransition({ kind: "clear", source }, ctx);
    },
    cancelProviderLimitAutoResume(_goalId, ctx) {
      providerLimitAutoResume.clear();
      status.refreshUi(ctx);
    },
    updateGoal,
    resumeGoalWithContinuation,
    ...eventHandlers,
  };
}

export function registerGoalRuntimeController(pi: ExtensionAPI): void {
  const controller = createGoalRuntimeController(pi);
  registerGoalTools(pi, {
    getGoal: () => controller.getGoalForDisplay(),
    setGoal: controller.setGoal.bind(controller),
    updateGoal: controller.updateGoal.bind(controller),
  });
  registerGoalCommand(pi, {
    getGoal: () => controller.getGoalForDisplay(),
    needsHostOverflowUserReset: controller.needsHostOverflowUserReset.bind(controller),
    setGoal: controller.setGoal.bind(controller),
    clearGoal: controller.clearGoal.bind(controller),
    editGoalObjective: controller.editGoalObjective.bind(controller),
    cancelProviderLimitAutoResume: controller.cancelProviderLimitAutoResume.bind(controller),
    resumeGoalWithContinuation: controller.resumeGoalWithContinuation.bind(controller),
  });
  registerGoalRuntimeEvents(pi, controller);
}
