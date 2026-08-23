"""
Phase 7d: Executor Interfaces
Abstractions for loosely-coupled executor design.

This module defines the core interfaces that the Executor depends on.
Implementations are in step_executor.py, context_manager.py, etc.

Design principle: Executor knows WHAT to do, not HOW to do it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import threading


# ============================================================================
# ENUMS
# ============================================================================

class StepStatus(Enum):
    """Status of a single step during execution."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


# ============================================================================
# ABSTRACT INTERFACES
# ============================================================================

class StepExecutor(ABC):
    """
    Abstract interface for executing a single step.
    
    Each ActionType has a corresponding StepExecutor implementation:
    - ToolStepExecutor: for READ_FILE, WRITE_FILE, etc.
    - ThinkStepExecutor: for THINK, DESIGN
    - SkillStepExecutor: for SKILL_WORKFLOW
    - VerifyStepExecutor: for RUN_TESTS, VERIFY
    """

    @abstractmethod
    def execute(self, step: "TaskStep", plan: "TaskPlan", context: "ContextManager") -> str:
        """
        Execute a single step.
        
        Args:
            step: The TaskStep to execute
            plan: The full TaskPlan (for context)
            context: ContextManager to access previous step outputs
        
        Returns:
            Output/result of the step (as string)
        
        Raises:
            StepExecutionError: If execution fails
        """
        pass


class ContextManager(ABC):
    """
    Abstract interface for managing step outputs during execution.
    
    Thread-safe. Handles:
    - Storing outputs from completed steps
    - Retrieving outputs for later steps (dependencies)
    - Providing snapshots for debugging
    """

    @abstractmethod
    def set_step_output(self, step_id: int, output: str) -> None:
        """Store output from a completed step."""
        pass

    @abstractmethod
    def get_step_output(self, step_id: int) -> str:
        """Retrieve output from a step (used by dependent steps)."""
        pass

    @abstractmethod
    def get_outputs_for_steps(self, step_ids: List[int]) -> Dict[int, str]:
        """Get outputs for multiple steps at once."""
        pass

    @abstractmethod
    def snapshot(self) -> Dict[int, str]:
        """Return a copy of all step outputs."""
        pass


class Logger(ABC):
    """
    Abstract interface for logging.
    Keeps audit trail of execution for debugging.
    """

    @abstractmethod
    def info(self, message: str) -> None:
        """Log info level message."""
        pass

    @abstractmethod
    def debug(self, message: str) -> None:
        """Log debug level message."""
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        """Log warning level message."""
        pass

    @abstractmethod
    def error(self, message: str) -> None:
        """Log error level message."""
        pass


class StepExecutorFactory(ABC):
    """
    Abstract factory for creating the right StepExecutor for an ActionType.
    """

    @abstractmethod
    def create(self, action_type: "ActionType") -> StepExecutor:
        """
        Create a StepExecutor for the given action type.
        
        Args:
            action_type: ActionType enum
        
        Returns:
            Appropriate StepExecutor instance
        
        Raises:
            ValueError: If action type is unknown
        """
        pass


# ============================================================================
# DATA CLASSES (used by Executor)
# ============================================================================

@dataclass
class ExecutionContext:
    """
    Context passed to each step executor.
    Contains everything the executor needs to do its job.
    """
    plan: "TaskPlan"
    context_manager: ContextManager
    logger: Logger
    execution_id: str  # For audit logging


@dataclass
class ExecutionResult:
    """
    Result of executing a full TaskPlan.
    """
    plan: "TaskPlan"
    completed_steps: Set[int]  # step IDs that succeeded
    failed_steps: Set[int]  # step IDs that failed
    skipped_steps: Set[int]  # step IDs that were skipped
    context_snapshot: Dict[int, str]  # all step outputs
    errors: Dict[int, str]  # step_id → error message
    
    def summary(self) -> str:
        """Human-readable summary of execution."""
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
                emoji = "✅"
                status_text = "COMPLETED"
            elif step_id in self.failed_steps:
                emoji = "❌"
                status_text = f"FAILED: {self.errors.get(step_id, 'unknown error')}"
            elif step_id in self.skipped_steps:
                emoji = "⊘"
                status_text = "SKIPPED"
            else:
                emoji = "⏳"
                status_text = "PENDING"
            
            lines.append(f"  {emoji} Step {step_id}: {step.description} ({status_text})")
        
        lines.append("=" * 60)
        return "\n".join(lines)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class ExecutionError(Exception):
    """Base class for execution-related errors."""
    pass


class StepExecutionError(ExecutionError):
    """Raised when a single step execution fails."""
    pass


class DependencyError(ExecutionError):
    """Raised when there are circular dependencies or missing steps."""
    pass


class TimeoutError(ExecutionError):
    """Raised when a step exceeds timeout."""
    pass


# ============================================================================
# TYPE STUBS (placeholders for task_plan.py types)
# ============================================================================

class TaskStep:
    """Placeholder - actual definition in task_plan.py"""
    step_id: int
    description: str
    action_type: "ActionType"
    depends_on: List[int]
    can_fail: bool
    status: StepStatus
    actual_output: Optional[str]
    error: Optional[str]
    tool_invocation: Optional[Any]


class TaskPlan:
    """Placeholder - actual definition in task_plan.py"""
    task_summary: str
    steps: List[TaskStep]
    skill_name: Optional[str]
    
    def topological_order(self) -> List[int]:
        """Return step IDs in dependency-respecting order."""
        pass


class ActionType(Enum):
    """Placeholder - actual definition in task_plan.py"""
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    SEARCH_CODE = "search_code"
    THINK = "think"
    DESIGN = "design"
    SKILL_WORKFLOW = "skill_workflow"
    RUN_TESTS = "run_tests"
    VERIFY = "verify"
    EDIT_FILE = "edit_file"
    LIST_FILES = "list_files"
    REVIEW_FINDINGS = "review_findings"
    RUN_LINTER = "run_linter"