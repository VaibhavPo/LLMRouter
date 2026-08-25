# src/core/executor/execution_state.py
"""
ExecutionState: what actually happened during this attempt.

The plan describes intended execution. This describes reality. The executor
consults this -- never just the original plan -- to decide what's done,
what's left, and what evidence has been gathered so far.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExecutionState:
    plan_id: str

    completed_steps: set[int] = field(default_factory=set)
    failed_steps: set[int] = field(default_factory=set)
    skipped_steps: set[int] = field(default_factory=set)

    step_outputs: dict[int, str] = field(default_factory=dict)
    """DEPRECATED as a write target: kept only as a read-compatible alias.
    Do not write to this directly -- PlanExecutionContext (ContextManager)
    is the single source of truth for step output text. Executor no longer
    populates this dict; anything that needs a step's output should take a
    ContextManager and call get_step_output(), not read execution_state
    .step_outputs. Retained (always empty, populated on demand via
    sync_outputs_from()) so external code that already reads it doesn't
    break outright -- but new code should not rely on it."""

    files_changed: list[str] = field(default_factory=list)
    artifacts_produced: list[str] = field(default_factory=list)

    # evidence_collected maps step_id -> a short evidence note (distinct from
    # the full step_outputs entry) -- what a checkpoint or replanner actually
    # relied on from that step, kept for the history record.
    evidence_collected: dict[int, str] = field(default_factory=dict)

    assumptions_confirmed: list[str] = field(default_factory=list)
    assumptions_invalidated: list[str] = field(default_factory=list)

    current_step_id: Optional[int] = None
    remaining_step_ids: list[int] = field(default_factory=list)

    replan_count: int = 0
    uncertain_resolution_attempts: int = 0

    def record_completed(self, step_id: int) -> None:
        self.completed_steps.add(step_id)
        self.failed_steps.discard(step_id)

    def record_failed(self, step_id: int, error: str) -> None:
        self.failed_steps.add(step_id)

    def record_skipped(self, step_id: int) -> None:
        self.skipped_steps.add(step_id)

    def sync_outputs_from(self, context) -> None:
        """
        Populate step_outputs from a ContextManager for callers that need a
        one-shot dict view (e.g. building a prompt over "everything gathered
        so far"). Not called automatically -- PlanExecutionContext remains
        the live source of truth; this is a snapshot, not a mirror.
        """
        self.step_outputs = context.get_outputs_for_steps(sorted(self.completed_steps))

    def record_invalidated_assumption(self, assumption: str) -> None:
        self.assumptions_invalidated.append(assumption)

    def record_confirmed_assumption(self, assumption: str) -> None:
        self.assumptions_confirmed.append(assumption)

    def snapshot(self) -> dict:
        """Plain-dict snapshot for persistence into ExecutionHistoryStore."""
        return {
            "plan_id": self.plan_id,
            "completed_steps": sorted(self.completed_steps),
            "failed_steps": sorted(self.failed_steps),
            "skipped_steps": sorted(self.skipped_steps),
            "files_changed": list(self.files_changed),
            "artifacts_produced": list(self.artifacts_produced),
            "assumptions_confirmed": list(self.assumptions_confirmed),
            "assumptions_invalidated": list(self.assumptions_invalidated),
            "current_step_id": self.current_step_id,
            "remaining_step_ids": list(self.remaining_step_ids),
            "replan_count": self.replan_count,
        }