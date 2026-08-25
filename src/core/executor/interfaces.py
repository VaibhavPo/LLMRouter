"""
Phase 7d: Executor Interfaces
Abstractions for loosely-coupled executor design.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
import threading

# Single source of truth for these types lives in task_plan.py.
# Do NOT redefine ActionType / StepStatus / TaskStep / TaskPlan here —
# a duplicate Enum class is never `==`/`in`-comparable to the real one,
# even with identical member names and values. That mismatch was the
# cause of "Unknown action type: ActionType.LIST_FILES".
from src.core.task_plan import ActionType, StepStatus, TaskStep, TaskPlan


# ============================================================================
# ABSTRACT INTERFACES
# ============================================================================

class StepExecutor(ABC):
    @abstractmethod
    def execute(self, step: "TaskStep", plan: "TaskPlan", context: "ContextManager") -> str:
        pass


class ContextManager(ABC):
    @abstractmethod
    def set_step_output(self, step_id: int, output: str) -> None:
        pass

    @abstractmethod
    def get_step_output(self, step_id: int) -> str:
        pass

    @abstractmethod
    def get_outputs_for_steps(self, step_ids: List[int]) -> Dict[int, str]:
        pass

    @abstractmethod
    def snapshot(self) -> Dict[int, str]:
        pass


class Logger(ABC):
    @abstractmethod
    def info(self, message: str) -> None:
        pass

    @abstractmethod
    def debug(self, message: str) -> None:
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        pass

    @abstractmethod
    def error(self, message: str) -> None:
        pass


class StepExecutorFactory(ABC):
    @abstractmethod
    def create(self, action_type: "ActionType") -> StepExecutor:
        pass


# ============================================================================
# DATA CLASSES (used by Executor)
# ============================================================================

@dataclass
class ExecutionContext:
    plan: "TaskPlan"
    context_manager: ContextManager
    logger: Logger
    execution_id: str


@dataclass
class ExecutionResult:
    plan: "TaskPlan"
    completed_steps: Set[int]
    failed_steps: Set[int]
    skipped_steps: Set[int]
    context_snapshot: Dict[int, str]
    errors: Dict[int, str]

    # Checkpoint/replan-loop bookkeeping (added for the checkpoint/evidence
    # architecture -- default values keep old call sites constructing
    # ExecutionResult without these still working).
    final_outcome: Optional[str] = None      # "success" | "failure" | "aborted"
    failure_reason: Optional[str] = None
    attempt_id: Optional[str] = None
    replan_count: int = 0

    def summary(self) -> str:
        total = len(self.plan.steps)
        passed = len(self.completed_steps)
        failed = len(self.failed_steps)
        skipped = len(self.skipped_steps)

        lines = [
            "\n" + "=" * 60,
            "EXECUTION SUMMARY",
            "=" * 60,
            f"Task: {self.plan.task_summary}",
            f"Steps: {passed}/{total} completed, {failed} failed, {skipped} skipped",
            "",
            "Step-by-step outcomes:",
        ]

        for step_id in range(len(self.plan.steps)):
            step = self.plan.steps[step_id]
            if step_id in self.completed_steps:
                emoji, status_text = "✅", "COMPLETED"
            elif step_id in self.failed_steps:
                emoji, status_text = "❌", f"FAILED: {self.errors.get(step_id, 'unknown error')}"
            elif step_id in self.skipped_steps:
                emoji, status_text = "⊘", "SKIPPED"
            else:
                emoji, status_text = "⏳", "PENDING"

            lines.append(f"  {emoji} Step {step_id}: {step.description} ({status_text})")

        lines.append("=" * 60)
        return "\n".join(lines)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class ExecutionError(Exception):
    pass


class StepExecutionError(ExecutionError):
    pass


class DependencyError(ExecutionError):
    pass


class TimeoutError(ExecutionError):
    pass