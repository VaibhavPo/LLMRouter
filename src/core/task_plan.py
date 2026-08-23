# src/core/task_plan.py
"""
TaskPlan schema: structured task representation for planner→executor handoff.

A TaskPlan is immutable, validated, and ready for execution.
Each step is independently verifiable and may use tools.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class ActionType(str, Enum):
    """Type of action a step performs."""
    
    # Information gathering (read-only, safe)
    READ_FILE = "read_file"              # Use read_file tool
    SEARCH_CODE = "search_code"          # Use search_code tool
    LIST_FILES = "list_files"            # Use list_files tool
    ANALYZE_CONTEXT = "analyze_context"  # Read CONTEXT.md, understand project state
    
    # Thinking/planning (no tools, pure reasoning)
    THINK = "think"                      # Model reasons through a problem
    DESIGN = "design"                    # Model designs a solution structure
    REVIEW_FINDINGS = "review_findings"  # Model reviews tool outputs and synthesizes
    
    # Code generation
    WRITE_FILE = "write_file"            # Use write_file tool (new file)
    EDIT_FILE = "edit_file"              # Use edit_file tool (modify existing)
    REFACTOR = "refactor"                # Rewrite code following a pattern
    
    # Execution and verification
    RUN_TESTS = "run_tests"              # Use run_tests tool
    RUN_LINTER = "run_linter"            # Use run_linter tool
    VERIFY = "verify"                    # Run any verification command
    
    # Special
    SKILL_WORKFLOW = "skill_workflow"    # Run a skill (TDD, Diagnosis, etc.)


class StepStatus(str, Enum):
    """Status of a step during execution."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ToolInvocation:
    """What tool to invoke and with what arguments."""
    
    tool_name: str                          # "read_file", "search_code", etc.
    arguments: dict[str, Any]               # {"file_path": "src/main.py", "start_line": 10}
    
    def __post_init__(self):
        """Validate tool invocation."""
        if not self.tool_name:
            raise ValueError("tool_name cannot be empty")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be a dict")


@dataclass
class TaskStep:
    """A single step in the task plan."""
    
    step_id: int                                    # 0, 1, 2, ... (index in plan)
    description: str                                # Human-readable what this step does
    action_type: ActionType                         # Type of action
    
    # Tool invocation (if action uses a tool)
    tool_invocation: Optional[ToolInvocation] = None
    
    # Why is this step needed?
    rationale: str = ""                            # "Needed to understand the current implementation"
    
    # Dependencies: which steps must complete first?
    depends_on: list[int] = field(default_factory=list)
    
    # What output do we expect?
    expected_output: str = ""                      # "A list of validation rules and field names"
    
    # Metadata
    estimated_time_seconds: int = 0                # ~how long should this take?
    can_fail: bool = False                         # Is it okay if this fails?
    failure_mode: str = ""                         # "If read fails, use CONTEXT.md instead"
    
    # Execution tracking (filled during execution)
    status: StepStatus = StepStatus.PENDING
    actual_output: Optional[str] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        """Validate step."""
        if self.step_id < 0:
            raise ValueError("step_id must be non-negative")
        
        if not self.description.strip():
            raise ValueError("description cannot be empty")
        
        if self.action_type in {ActionType.READ_FILE, ActionType.SEARCH_CODE, 
                                ActionType.LIST_FILES, ActionType.WRITE_FILE, 
                                ActionType.EDIT_FILE}:
            if self.tool_invocation is None:
                raise ValueError(f"{self.action_type} requires tool_invocation")
        
        if any(dep >= self.step_id for dep in self.depends_on):
            raise ValueError("step cannot depend on itself or later steps")
    
    def is_ready(self, completed_steps: set[int]) -> bool:
        """Check if all dependencies are satisfied."""
        return all(dep in completed_steps for dep in self.depends_on)
    
    def is_complete(self) -> bool:
        """Check if step has finished (success or allowed failure)."""
        return self.status in {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED}


@dataclass
class TaskPlan:
    """A complete task plan: ordered steps with dependencies."""
    
    task_summary: str                               # One-liner: "Add validation to UserSchema"
    steps: list[TaskStep]                           # Ordered list of steps
    
    # Which files are relevant to this task?
    relevant_files: list[str] = field(default_factory=list)
    
    # Skill to use (if any)
    skill_name: Optional[str] = None               # "TDD", "Diagnosis", None
    
    # Total estimated time
    estimated_total_seconds: int = 0
    
    # Context budget: how many tokens should planner use?
    estimated_tokens_used: int = 0
    
    def __post_init__(self):
        """Validate plan."""
        if not self.task_summary.strip():
            raise ValueError("task_summary cannot be empty")
        
        if not self.steps:
            raise ValueError("plan must have at least one step")
        
        # Check step IDs are sequential
        for i, step in enumerate(self.steps):
            if step.step_id != i:
                raise ValueError(f"step IDs must be sequential; got {step.step_id} at position {i}")
        
        # Estimate total time
        if self.estimated_total_seconds == 0:
            self.estimated_total_seconds = sum(s.estimated_time_seconds for s in self.steps)
    
    def get_next_ready_step(self, completed_steps: set[int]) -> Optional[TaskStep]:
        """Get the next step that's ready to execute (dependencies satisfied)."""
        for step in self.steps:
            if step.status == StepStatus.PENDING and step.is_ready(completed_steps):
                return step
        return None
    
    def topological_order(self) -> list[int]:
        """Get execution order respecting dependencies."""
        order = []
        completed = set()
        
        while len(order) < len(self.steps):
            step = self.get_next_ready_step(completed)
            if step is None:
                # Circular dependency or unreachable step
                raise ValueError("Plan has circular dependencies or unreachable steps")
            
            order.append(step.step_id)
            completed.add(step.step_id)
        
        return order


@dataclass
class PlannerResponse:
    """What the planner model returns."""
    
    plan: TaskPlan
    reasoning: str                     # Why the planner chose this plan
    alternatives_considered: list[str] = field(default_factory=list)
    
    def summary(self) -> str:
        """Human-readable summary of the plan."""
        lines = [
            f"Task: {self.plan.task_summary}",
            f"Skill: {self.plan.skill_name or 'None'}",
            f"Steps: {len(self.plan.steps)}",
            f"Est. time: {self.plan.estimated_total_seconds}s",
            "",
            "Step sequence:",
        ]
        
        for step in self.plan.steps:
            indent = "  " if step.depends_on else ""
            deps_str = f" (needs: steps {step.depends_on})" if step.depends_on else ""
            lines.append(f"{indent}{step.step_id}. {step.description}{deps_str}")
        
        return "\n".join(lines)