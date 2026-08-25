"""
Phase 7d/migration: Executor -- checkpoint/evidence-based adaptive execution.

Replaces the pure linear "run steps in dependency order, retry-or-abort on
failure" executor with the state machine from ARCHITECTURE_AFTER_STEP4.md:

    EXECUTING -> STEP_SUCCESS -> checkpoint? -> VALID/UNCERTAIN/INVALID/UNRECOVERABLE
    INVALID -> LOCAL_REPLAN -> EXECUTING (repaired tail, completed steps preserved)
    ALL_STEPS_COMPLETE -> FINAL_VALIDATION -> PASS -> SUCCESS
                                            -> FAIL -> FULL_REPLAN -> EXECUTING

The Executor still does not invent tasks on its own (Invariant 9). It only
ever runs steps that are in the current plan, and only ever changes the
current plan via LocalReplanner/FullReplanner -- never ad hoc.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Set

import time

from src.core.executor.interfaces import (
    StepExecutor,
    ContextManager,
    Logger,
    StepExecutorFactory,
    ExecutionResult,
    ExecutionError,
    StepExecutionError,
    StepStatus,
    DependencyError,
)
from src.core.executor.execution_state import ExecutionState
from src.core.executor.checkpoint import (
    CheckpointEvaluator,
    CheckpointVerdict,
    CheckpointError,
)
from src.core.executor.replanner import (
    Replanner,
    ReplanRequest,
    ReplanError,
)
from src.core.executor.final_validation import (
    FinalValidator,
    NoopFinalValidator,
    FinalOutcome,
)


@dataclass
class ExecutorConfig:
    max_replans: int = 3                 # total across local + full, per attempt
    uncertain_retry_limit: int = 1        # extra "deeper" checkpoint calls before escalating
    timeout_per_step: int = 300


class UnrecoverableExecutionError(ExecutionError):
    """Raised internally when a checkpoint returns UNRECOVERABLE, or when
    replanning itself fails/is exhausted. Always caught by execute() and
    turned into a persisted, structured failure -- never propagated raw."""
    pass


class Executor:
    """
    Orchestrator for executing TaskPlans with checkpoint-triggered adaptive
    replanning. Loosely coupled: depends on interfaces (StepExecutorFactory,
    ContextManager, Logger, CheckpointEvaluator, Replanner, FinalValidator),
    not implementations.

    checkpoint_evaluator, local_replanner are required -- there is no
    meaningful checkpoint/replan architecture without them. full_replanner
    and history_store are optional: without a full_replanner, a FAIL final
    validation is reported as a plain failure instead of triggering
    FULL_REPLAN; without a history_store, attempts simply aren't persisted.
    """

    def __init__(
        self,
        step_executor_factory: StepExecutorFactory,
        context_manager: ContextManager,
        logger: Logger,
        checkpoint_evaluator: CheckpointEvaluator,
        local_replanner: Replanner,
        full_replanner: Optional[Replanner] = None,
        final_validator: Optional[FinalValidator] = None,
        history_store=None,
        config: Optional[ExecutorConfig] = None,
    ):
        self.step_executor_factory = step_executor_factory
        self.context = context_manager
        self.logger = logger
        self.checkpoint_evaluator = checkpoint_evaluator
        self.local_replanner = local_replanner
        self.full_replanner = full_replanner
        self.final_validator = final_validator or NoopFinalValidator()
        self.history = history_store
        self.config = config or ExecutorConfig()

    # -- public entry point --------------------------------------------------

    def execute(self, plan, task_id: str, original_task: str) -> ExecutionResult:
        """
        Execute a TaskPlan to completion, adapting to evidence along the way.

        task_id identifies this *task* across attempts (used for history
        lookup / relevant_history_text on the next planning call).
        original_task is the human-readable goal, persisted alongside it.
        """
        attempt_id = None
        if self.history is not None:
            attempt_id = self.history.start_attempt(task_id, original_task, plan)

        state = ExecutionState(plan_id=plan.plan_id)
        current_plan = plan

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"EXECUTION START: {current_plan.task_summary}")
        self.logger.info(f"{'='*60}")

        try:
            while True:
                outcome = self._run_until_complete_or_blocked(current_plan, state, attempt_id)

                if outcome == "unrecoverable":
                    return self._finish(current_plan, state, attempt_id, "aborted",
                                         self._last_failure_reason)

                # outcome == "all_steps_complete" -> final goal validation
                self.logger.info("All steps complete -- running final goal validation")
                validation = self.final_validator.validate(current_plan, state)

                if validation.outcome == FinalOutcome.PASS:
                    self.logger.info(f"Final validation: PASS ({validation.reasoning})")
                    return self._finish(current_plan, state, attempt_id, "success", None)

                self.logger.warning(f"Final validation: FAIL ({validation.reasoning})")

                if self.full_replanner is None or state.replan_count >= self.config.max_replans:
                    reason = f"final validation failed and no full replan available: {validation.reasoning}"
                    return self._finish(current_plan, state, attempt_id, "failure", reason)

                current_plan = self._do_full_replan(current_plan, state, attempt_id, validation.reasoning)
                if current_plan is None:
                    return self._finish(current_plan or plan, state, attempt_id, "aborted",
                                         self._last_failure_reason)
                # loop again with the fully-replanned plan

        except UnrecoverableExecutionError as e:
            return self._finish(current_plan, state, attempt_id, "aborted", str(e))

    # -- internals -------------------------------------------------------------

    def _finish(self, plan, state: ExecutionState, attempt_id, outcome: str,
                failure_reason: Optional[str]) -> ExecutionResult:
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"EXECUTION {outcome.upper()}")
        self.logger.info(f"{'='*60}")

        if self.history is not None and attempt_id is not None:
            self.history.finalize_attempt(attempt_id, outcome, failure_reason=failure_reason)

        return ExecutionResult(
            plan=plan,
            completed_steps=set(state.completed_steps),
            failed_steps=set(state.failed_steps),
            skipped_steps=set(state.skipped_steps),
            context_snapshot=self.context.snapshot(),
            errors={},
            final_outcome=outcome,
            failure_reason=failure_reason,
            attempt_id=attempt_id,
            replan_count=state.replan_count,
        )

    def _run_until_complete_or_blocked(self, plan, state: ExecutionState, attempt_id) -> str:
        """
        Runs steps of `plan` (mutated via local replans in place, by rebinding
        the caller's `current_plan` -- see the trampoline below) until either:
          - every step is completed/skipped -> returns "all_steps_complete"
          - an UNRECOVERABLE verdict/failure occurs -> returns "unrecoverable"

        Note: because a local replan produces a NEW TaskPlan object (repair,
        don't mutate), this method needs to be able to swap the plan out from
        under itself mid-loop. It does this by returning control to execute()
        via a small internal trampoline (self._current_plan_ref) rather than
        threading the plan through every recursive call.
        """
        self._current_plan_ref = plan
        self._last_failure_reason = None

        while True:
            active_plan = self._current_plan_ref
            completed_and_skipped = state.completed_steps | state.skipped_steps
            next_step = active_plan.get_next_ready_step(completed_and_skipped)

            if next_step is None:
                if len(completed_and_skipped) + len(state.failed_steps) >= len(active_plan.steps):
                    return "all_steps_complete"
                # Nothing ready but plan isn't finished either -> everything
                # remaining is blocked on a failed, non-skippable dependency.
                self._last_failure_reason = "remaining steps are blocked on a failed dependency"
                return "unrecoverable"

            state.current_step_id = next_step.step_id
            state.remaining_step_ids = [
                s.step_id for s in active_plan.steps
                if s.step_id not in state.completed_steps and s.step_id not in state.skipped_steps
            ]

            try:
                self._execute_step(next_step, active_plan, state)
            except StepExecutionError as e:
                self._handle_step_failure(next_step, active_plan, state, attempt_id, str(e))
                if self._last_failure_reason:
                    return "unrecoverable"
                continue  # skipped, keep going

            state.record_completed(next_step.step_id, next_step.actual_output or "")
            if self.history is not None and attempt_id is not None:
                self.history.record_step_completed(attempt_id, next_step.step_id, next_step.actual_output or "")

            if next_step.can_replan:
                verdict_result = self._run_checkpoint(next_step, active_plan, state, attempt_id)
                if verdict_result == "unrecoverable":
                    return "unrecoverable"
                # verdict_result == "continue": active_plan may have been
                # swapped by a local replan; loop picks up self._current_plan_ref

    def _execute_step(self, step, plan, state: ExecutionState) -> None:
        self.logger.info(f"\nExecuting step {step.step_id}: {step.description}")
        step.status = StepStatus.IN_PROGRESS
        start_time = time.time()

        try:
            executor: StepExecutor = self.step_executor_factory.create(step.action_type)
            result = executor.execute(step, plan, self.context)

            step.actual_output = result
            step.status = StepStatus.COMPLETED
            self.context.set_step_output(step.step_id, result)

            elapsed = time.time() - start_time
            self.logger.info(f"Step {step.step_id}: completed in {elapsed:.2f}s")

        except Exception as e:
            elapsed = time.time() - start_time
            step.status = StepStatus.FAILED
            step.error = str(e)
            raise StepExecutionError(
                f"Step {step.step_id} execution failed after {elapsed:.2f}s: {e}"
            )

    def _handle_step_failure(self, step, plan, state: ExecutionState, attempt_id, error_msg: str) -> None:
        self.logger.error(f"Step {step.step_id}: FAILED -- {error_msg}")
        state.record_failed(step.step_id, error_msg)

        if self.history is not None and attempt_id is not None:
            self.history.record_execution_failure(attempt_id, step.step_id, error_msg)

        if step.can_fail:
            self.logger.info(f"Skipping step {step.step_id} (can_fail=True)")
            step.status = StepStatus.SKIPPED
            state.record_skipped(step.step_id)
            self._last_failure_reason = None
            return

        self._last_failure_reason = (
            f"step {step.step_id} failed and cannot be skipped: {error_msg}"
        )

    def _run_checkpoint(self, step, plan, state: ExecutionState, attempt_id) -> str:
        """Returns "continue" or "unrecoverable"."""
        try:
            result = self.checkpoint_evaluator.evaluate(step, plan, self.context, state)
        except CheckpointError as e:
            # Never silently assume VALID on a checkpoint failure -- treat
            # exactly like an unresolved UNCERTAIN verdict.
            self.logger.warning(f"Checkpoint for step {step.step_id} failed: {e}")
            result = None
            verdict = CheckpointVerdict.UNCERTAIN
            reasoning = f"checkpoint evaluator error: {e}"
            invalidated_assumption = None
        else:
            verdict = result.verdict
            reasoning = result.reasoning
            invalidated_assumption = result.invalidated_assumption

        if self.history is not None and attempt_id is not None:
            self.history.record_checkpoint_decision(attempt_id, step.step_id, verdict.value, reasoning)

        self.logger.info(f"Checkpoint step {step.step_id}: {verdict.value} -- {reasoning}")

        if verdict == CheckpointVerdict.VALID:
            state.record_confirmed_assumption(reasoning)
            return "continue"

        if verdict == CheckpointVerdict.UNCERTAIN:
            if state.uncertain_resolution_attempts < self.config.uncertain_retry_limit:
                state.uncertain_resolution_attempts += 1
                self.logger.info(f"Uncertain -- gathering deeper evidence for step {step.step_id}")
                try:
                    deeper = self.checkpoint_evaluator.evaluate(step, plan, self.context, state, deeper=True)
                except CheckpointError as e:
                    self.logger.warning(f"Deeper checkpoint also failed: {e}")
                    deeper = None
                if deeper is not None and deeper.verdict != CheckpointVerdict.UNCERTAIN:
                    verdict = deeper.verdict
                    reasoning = deeper.reasoning
                    invalidated_assumption = deeper.invalidated_assumption
                    if self.history is not None and attempt_id is not None:
                        self.history.record_checkpoint_decision(attempt_id, step.step_id, verdict.value, reasoning)
                    if verdict == CheckpointVerdict.VALID:
                        state.record_confirmed_assumption(reasoning)
                        return "continue"
                    # fall through to INVALID/UNRECOVERABLE handling below
                else:
                    # still uncertain after gathering more evidence -- treat
                    # as invalid: we know the plan MIGHT be wrong and have no
                    # cheap way left to find out, so repair rather than guess.
                    verdict = CheckpointVerdict.INVALID
                    invalidated_assumption = invalidated_assumption or (
                        f"uncertainty after step {step.step_id} could not be resolved"
                    )
            else:
                verdict = CheckpointVerdict.INVALID
                invalidated_assumption = invalidated_assumption or (
                    f"uncertainty after step {step.step_id} exceeded retry limit"
                )

        if verdict == CheckpointVerdict.UNRECOVERABLE:
            self._last_failure_reason = f"checkpoint at step {step.step_id} declared unrecoverable: {reasoning}"
            return "unrecoverable"

        # verdict == INVALID
        return self._do_local_replan(step, plan, state, attempt_id, invalidated_assumption, reasoning)

    def _do_local_replan(self, step, plan, state: ExecutionState, attempt_id,
                          invalidated_assumption: Optional[str], evidence: str) -> str:
        if state.replan_count >= self.config.max_replans:
            self._last_failure_reason = (
                f"replan limit ({self.config.max_replans}) reached at step {step.step_id}"
            )
            return "unrecoverable"

        self.logger.info(f"INVALID checkpoint -> local replan from step {step.step_id + 1}")
        request = ReplanRequest(
            original_plan=plan,
            execution_state=state,
            invalidated_assumption=invalidated_assumption or "(unspecified)",
            new_evidence=evidence,
        )
        try:
            new_plan = self.local_replanner.replan(request)
        except ReplanError as e:
            self.logger.error(f"Local replan failed: {e}")
            if self.history is not None and attempt_id is not None:
                self.history.record_execution_failure(attempt_id, step.step_id, f"local replan failed: {e}")
            self._last_failure_reason = f"local replan failed: {e}"
            return "unrecoverable"

        state.replan_count += 1
        if invalidated_assumption:
            state.record_invalidated_assumption(invalidated_assumption)

        if self.history is not None and attempt_id is not None:
            self.history.record_replan(
                attempt_id, kind="local", reason=evidence,
                invalidated_assumption=invalidated_assumption or "",
                new_plan_id=new_plan.plan_id,
            )

        self._current_plan_ref = new_plan
        return "continue"

    def _do_full_replan(self, plan, state: ExecutionState, attempt_id, failure_reason: str):
        self.logger.info("FULL_REPLAN: reconsidering task from the beginning")
        history_text = ""
        if self.history is not None:
            # relevant_history_text reads from task_id, but Executor.execute()
            # doesn't retain task_id here by design (state machine shouldn't
            # need it past attempt start) -- callers who want richer full-
            # replan context should pass a history-aware full_replanner.
            history_text = ""

        request = ReplanRequest(
            original_plan=plan,
            execution_state=state,
            invalidated_assumption="",
            new_evidence="",
            failure_reason=failure_reason,
            previous_attempts_summary=history_text,
        )
        try:
            new_plan = self.full_replanner.replan(request)
        except ReplanError as e:
            self.logger.error(f"Full replan failed: {e}")
            if self.history is not None and attempt_id is not None:
                self.history.record_execution_failure(attempt_id, -1, f"full replan failed: {e}")
            self._last_failure_reason = f"full replan failed: {e}"
            return None

        state.replan_count += 1
        if self.history is not None and attempt_id is not None:
            self.history.record_replan(
                attempt_id, kind="full", reason=failure_reason, new_plan_id=new_plan.plan_id,
            )
        return new_plan


# ============================================================================
# BUILDER / CONFIGURATION
# ============================================================================

class ExecutorBuilder:
    """Wires a fully-configured Executor. tool_runtime is required; the model
    providers passed to build() should be the CHEAP tier for checkpoint_model
    and the STRONG tier for replan_model/final_validation_model, per Model
    Policy (Section 18)."""

    def __init__(self, tool_runtime, logger=None):
        self.tool_runtime = tool_runtime
        self.logger = logger or ConsoleLogger()

    def build(
        self,
        model_provider,
        skill_factory,
        checkpoint_model_provider,
        replan_model_provider=None,
        final_validation_model_provider=None,
        history_storage_dir: Optional[str] = None,
        config: Optional[ExecutorConfig] = None,
    ) -> Executor:
        from src.core.executor.step_executor import DefaultStepExecutorFactory
        from src.core.executor.context_manager import PlanExecutionContext
        from src.core.executor.checkpoint import ModelCheckpointEvaluator
        from src.core.executor.replanner import LocalReplanner, FullReplanner
        from src.core.executor.final_validation import ModelFinalValidator, NoopFinalValidator

        replan_model_provider = replan_model_provider or model_provider

        step_executor_factory = DefaultStepExecutorFactory(
            tool_runtime=self.tool_runtime,
            model_provider=model_provider,
            skill_factory=skill_factory,
        )
        context_manager = PlanExecutionContext()
        checkpoint_evaluator = ModelCheckpointEvaluator(checkpoint_model_provider)
        local_replanner = LocalReplanner(replan_model_provider)
        full_replanner = FullReplanner(replan_model_provider)

        final_validator = (
            ModelFinalValidator(final_validation_model_provider)
            if final_validation_model_provider else NoopFinalValidator()
        )

        history_store = None
        if history_storage_dir:
            from src.core.executor.execution_history import ExecutionHistoryStore
            history_store = ExecutionHistoryStore(history_storage_dir)

        return Executor(
            step_executor_factory=step_executor_factory,
            context_manager=context_manager,
            logger=self.logger,
            checkpoint_evaluator=checkpoint_evaluator,
            local_replanner=local_replanner,
            full_replanner=full_replanner,
            final_validator=final_validator,
            history_store=history_store,
            config=config,
        )


# ============================================================================
# LOGGING
# ============================================================================

class ConsoleLogger(Logger):
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def info(self, message: str) -> None:
        if self.verbose:
            print(f"[INFO] {message}")

    def debug(self, message: str) -> None:
        if self.verbose:
            print(f"[DEBUG] {message}")

    def warning(self, message: str) -> None:
        print(f"[WARNING] {message}")

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}")


class SilentLogger(Logger):
    def info(self, message: str) -> None:
        pass

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass