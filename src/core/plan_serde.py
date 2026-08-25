# src/core/plan_serde.py
"""
Shared serialization between LLM JSON output and TaskPlan/TaskStep objects.

Used by:
- Planner (initial plan generation)
- LocalReplanner (tail-only plan repair)
- FullReplanner (whole-plan regeneration)

Keeping this in one place means all three producers of a TaskPlan build
objects the same way, with the same error behavior on malformed LLM output.
"""

from typing import Any, Optional

from src.core.task_plan import (
    ActionType,
    StepStatus,
    TaskStep,
    TaskPlan,
    ToolInvocation,
)


class PlanParseError(ValueError):
    """Raised when LLM JSON cannot be turned into valid TaskStep/TaskPlan objects."""
    pass


def dict_to_tool_invocation(d: Optional[dict]) -> Optional[ToolInvocation]:
    if d is None:
        return None
    try:
        return ToolInvocation(
            tool_name=d["tool_name"],
            arguments=d.get("arguments", {}),
        )
    except KeyError as e:
        raise PlanParseError(f"tool_invocation missing required field: {e}")


def dict_to_task_step(d: dict, step_id: int) -> TaskStep:
    """
    Build a TaskStep from a raw dict produced by an LLM.

    step_id is passed explicitly (rather than trusted from the dict) because
    replanned tails are renumbered by the caller (see plan_serde.renumber_steps
    / TaskPlan.with_replaced_tail) -- the LLM should not be relied on to know
    the final step_id of a step it's proposing mid-repair.
    """
    try:
        action_type = ActionType(d["action_type"])
    except KeyError:
        raise PlanParseError(f"step missing 'action_type': {d}")
    except ValueError:
        raise PlanParseError(f"unknown action_type '{d.get('action_type')}': {d}")

    try:
        description = d["description"]
    except KeyError:
        raise PlanParseError(f"step missing 'description': {d}")

    try:
        return TaskStep(
            step_id=step_id,
            description=description,
            action_type=action_type,
            tool_invocation=dict_to_tool_invocation(d.get("tool_invocation")),
            rationale=d.get("rationale", ""),
            depends_on=list(d.get("depends_on", [])),
            expected_output=d.get("expected_output", ""),
            estimated_time_seconds=d.get("estimated_time_seconds", 0),
            can_fail=d.get("can_fail", False),
            failure_mode=d.get("failure_mode", ""),
            can_replan=d.get("can_replan", False),
            status=StepStatus.PENDING,
        )
    except ValueError as e:
        # TaskStep.__post_init__ validation failure (bad step_id, empty
        # description, self/forward dependency, missing tool_invocation, ...)
        raise PlanParseError(f"invalid step {step_id}: {e}")


def dict_to_task_plan(d: dict) -> TaskPlan:
    """Build a full TaskPlan from a raw dict produced by an LLM (initial planning)."""
    try:
        task_summary = d["task_summary"]
        raw_steps = d["steps"]
    except KeyError as e:
        raise PlanParseError(f"plan missing required field: {e}")

    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanParseError("plan 'steps' must be a non-empty list")

    steps = [dict_to_task_step(s, i) for i, s in enumerate(raw_steps)]

    try:
        return TaskPlan(
            task_summary=task_summary,
            steps=steps,
            relevant_files=list(d.get("relevant_files", [])),
            skill_name=d.get("skill_name"),
            estimated_tokens_used=d.get("estimated_tokens_used", 0),
        )
    except ValueError as e:
        raise PlanParseError(f"invalid plan: {e}")


def dict_list_to_step_tail(raw_steps: list[dict], first_step_id: int) -> list[TaskStep]:
    """
    Build a sequential run of TaskSteps starting at first_step_id, used for
    local-replan tails. depends_on values in raw_steps may reference either
    earlier (already-completed, out-of-range-low) step_ids or other steps
    within this same tail using their *final* renumbered ids -- callers
    (LocalReplanner) are responsible for asking the LLM to use final ids.
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanParseError("replan 'steps' must be a non-empty list")

    steps = []
    for offset, s in enumerate(raw_steps):
        step_id = first_step_id + offset
        steps.append(dict_to_task_step(s, step_id))
    return steps