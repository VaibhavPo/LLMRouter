# src/core/executor/execution_history.py
"""
ExecutionHistoryStore: persists the full lifecycle of each task attempt.

Deliberately separate from ContextStore (CONTEXT.md). ContextStore holds
long-lived project knowledge (structure, conventions, important files).
This store holds attempt-specific knowledge: what was tried, what failed,
what evidence caused the failure, what was replanned. It exists to change
future planning -- exposing relevant_history() to the Planner is what makes
a second attempt capable of producing a meaningfully different plan.

File-based, one JSON file per attempt, mirroring the project's existing
file-based ContextStore convention:

    {storage_dir}/{task_id}/{attempt_id}.json

Rewritten in full on every state-changing call. Attempts are small
(a handful of steps, a handful of decisions) so this is cheap and gives
crash-safety for free -- there's no risk of losing history to a process
that dies mid-attempt, at the cost of a full-file rewrite per event.
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class PlanningFailureRecord:
    timestamp: float
    error: str
    raw_response: str = ""


@dataclass
class ExecutionFailureRecord:
    timestamp: float
    step_id: int
    error: str
    evidence: str = ""


@dataclass
class CheckpointDecisionRecord:
    timestamp: float
    step_id: int
    verdict: str
    reasoning: str


@dataclass
class ReplanRecord:
    timestamp: float
    kind: str                          # "local" | "full"
    reason: str
    invalidated_assumption: str = ""
    new_plan_id: str = ""


@dataclass
class AttemptRecord:
    attempt_id: str
    task_id: str
    started_at: float
    original_task: str
    initial_plan_id: str
    initial_plan_summary: str

    planning_failures: list = field(default_factory=list)
    validated_plan_id: Optional[str] = None
    completed_steps: list = field(default_factory=list)
    step_outputs_summary: dict = field(default_factory=dict)
    execution_failures: list = field(default_factory=list)
    checkpoint_decisions: list = field(default_factory=list)
    replans: list = field(default_factory=list)
    invalidated_assumptions: list = field(default_factory=list)

    final_outcome: Optional[str] = None    # "success" | "failure" | "aborted"
    failure_reason: Optional[str] = None
    artifacts: list = field(default_factory=list)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AttemptRecord":
        return AttemptRecord(**d)


def _truncate(s: str, limit: int = 500) -> str:
    return s if len(s) <= limit else s[:limit] + f"...[+{len(s) - limit} chars]"


class ExecutionHistoryStore:
    """
    Usage:
        history = ExecutionHistoryStore(storage_dir="./history")

        attempt_id = history.start_attempt(
            task_id="add-email-validation",
            original_task="Add email validation to UserSchema",
            initial_plan=plan,
        )
        history.record_checkpoint_decision(attempt_id, step_id=1,
                                            verdict="invalid",
                                            reasoning="file moved")
        history.record_replan(attempt_id, kind="local", reason="...",
                               invalidated_assumption="...", new_plan_id="...")
        history.finalize_attempt(attempt_id, outcome="success")

        # Next planning call for the same task_id:
        context_for_planner = history.relevant_history_text(task_id="add-email-validation")
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self._active: dict[str, AttemptRecord] = {}

    # -- paths -----------------------------------------------------------

    def _task_dir(self, task_id: str) -> str:
        d = os.path.join(self.storage_dir, task_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _attempt_path(self, task_id: str, attempt_id: str) -> str:
        return os.path.join(self._task_dir(task_id), f"{attempt_id}.json")

    def _persist(self, record: AttemptRecord) -> None:
        path = self._attempt_path(record.task_id, record.attempt_id)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
        os.replace(tmp_path, path)   # atomic on POSIX

    def _get_active(self, attempt_id: str) -> AttemptRecord:
        if attempt_id not in self._active:
            raise KeyError(
                f"attempt_id {attempt_id} is not an active attempt in this "
                f"ExecutionHistoryStore instance (finalized or from a "
                f"different process -- reload with get_attempt() instead)"
            )
        return self._active[attempt_id]

    # -- lifecycle ---------------------------------------------------------

    def start_attempt(self, task_id: str, original_task: str, initial_plan) -> str:
        attempt_id = str(uuid.uuid4())
        record = AttemptRecord(
            attempt_id=attempt_id,
            task_id=task_id,
            started_at=time.time(),
            original_task=original_task,
            initial_plan_id=initial_plan.plan_id,
            initial_plan_summary=initial_plan.task_summary,
        )
        self._active[attempt_id] = record
        self._persist(record)
        return attempt_id

    def record_planning_failure(self, attempt_id: str, error: str, raw_response: str = "") -> None:
        record = self._get_active(attempt_id)
        record.planning_failures.append(
            PlanningFailureRecord(time.time(), error, _truncate(raw_response)).__dict__
        )
        self._persist(record)

    def record_validated_plan(self, attempt_id: str, plan_id: str) -> None:
        record = self._get_active(attempt_id)
        record.validated_plan_id = plan_id
        self._persist(record)

    def record_step_completed(self, attempt_id: str, step_id: int, output: str) -> None:
        record = self._get_active(attempt_id)
        if step_id not in record.completed_steps:
            record.completed_steps.append(step_id)
        record.step_outputs_summary[str(step_id)] = _truncate(output, 200)
        self._persist(record)

    def record_execution_failure(self, attempt_id: str, step_id: int, error: str, evidence: str = "") -> None:
        record = self._get_active(attempt_id)
        record.execution_failures.append(
            ExecutionFailureRecord(time.time(), step_id, error, _truncate(evidence)).__dict__
        )
        self._persist(record)

    def record_checkpoint_decision(self, attempt_id: str, step_id: int, verdict: str, reasoning: str) -> None:
        record = self._get_active(attempt_id)
        record.checkpoint_decisions.append(
            CheckpointDecisionRecord(time.time(), step_id, verdict, reasoning).__dict__
        )
        self._persist(record)

    def record_replan(self, attempt_id: str, kind: str, reason: str,
                       invalidated_assumption: str = "", new_plan_id: str = "") -> None:
        record = self._get_active(attempt_id)
        record.replans.append(
            ReplanRecord(time.time(), kind, reason, invalidated_assumption, new_plan_id).__dict__
        )
        if invalidated_assumption and invalidated_assumption not in record.invalidated_assumptions:
            record.invalidated_assumptions.append(invalidated_assumption)
        self._persist(record)

    def finalize_attempt(self, attempt_id: str, outcome: str,
                          failure_reason: Optional[str] = None,
                          artifacts: Optional[list] = None) -> AttemptRecord:
        record = self._get_active(attempt_id)
        record.final_outcome = outcome
        record.failure_reason = failure_reason
        record.artifacts = artifacts or []
        record.finished_at = time.time()
        self._persist(record)
        del self._active[attempt_id]
        return record

    # -- reads for future planning ------------------------------------------

    def get_attempts(self, task_id: str) -> list[AttemptRecord]:
        task_dir = self._task_dir(task_id)
        attempts = []
        for fname in sorted(os.listdir(task_dir)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(task_dir, fname)) as f:
                attempts.append(AttemptRecord.from_dict(json.load(f)))
        attempts.sort(key=lambda a: a.started_at)
        return attempts

    def relevant_history_text(self, task_id: str, max_attempts: int = 3) -> str:
        """
        Formatted summary handed to the planner for a repeated task, per
        Invariant 10 (attempt awareness). Empty string if there's no history
        -- callers should treat that as "first attempt", not an error.
        """
        attempts = self.get_attempts(task_id)
        if not attempts:
            return ""

        lines = [f"Previous attempts at this task ({len(attempts)} total):"]
        for attempt in attempts[-max_attempts:]:
            lines.append(f"\n- Attempt {attempt.attempt_id[:8]} ({attempt.final_outcome or 'in progress'}):")
            if attempt.planning_failures:
                lines.append(f"  Planning failures: {[pf['error'] for pf in attempt.planning_failures]}")
            if attempt.execution_failures:
                lines.append(f"  Execution failures: {[ef['error'] for ef in attempt.execution_failures]}")
            if attempt.invalidated_assumptions:
                lines.append(f"  Invalidated assumptions: {attempt.invalidated_assumptions}")
            if attempt.failure_reason:
                lines.append(f"  Failure reason: {attempt.failure_reason}")
            if attempt.completed_steps:
                lines.append(f"  Steps that succeeded: {attempt.completed_steps}")
        return "\n".join(lines)