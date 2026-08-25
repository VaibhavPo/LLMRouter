# src/core/executor/replanner.py
"""
Replanning: repair, not restart.

LocalReplanner is invoked on a checkpoint INVALID verdict. It receives only
the untouched (not-yet-completed) portion of the plan and produces a new
tail; completed steps are never regenerated (TaskPlan.with_replaced_tail
enforces this).

FullReplanner is invoked on final-goal-validation FAIL. It reconsiders the
task from the beginning but is still handed everything gathered so far
(execution state + history) -- it must not pretend nothing happened.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from src.core.task_plan import TaskPlan
from src.core.plan_serde import dict_list_to_step_tail, dict_to_task_plan, PlanParseError
from src.core.executor.execution_state import ExecutionState


class ReplanError(Exception):
    """Replanning itself failed (model error, unparseable/invalid response).
    Distinct from the plan being replanned being wrong -- this means we
    couldn't produce a replacement at all. Callers persist this as an
    execution failure and count it toward the replan limit."""
    pass


@dataclass
class ReplanRequest:
    original_plan: TaskPlan
    execution_state: ExecutionState
    invalidated_assumption: str
    new_evidence: str
    failure_reason: Optional[str] = None
    previous_attempts_summary: str = ""


class Replanner(ABC):
    @abstractmethod
    def replan(self, request: ReplanRequest) -> TaskPlan:
        ...


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(text: str) -> dict:
    cleaned = _JSON_FENCE.sub("", text).strip()
    return json.loads(cleaned)


def _completed_steps_desc(plan: TaskPlan, execution_state: ExecutionState) -> str:
    lines = []
    for step in plan.steps:
        if step.step_id in execution_state.completed_steps:
            lines.append(f"  {step.step_id}. {step.description} -> {step.actual_output or ''}"[:300])
    return "\n".join(lines) or "  (none)"


class LocalReplanner(Replanner):
    """
    Uses the strong/high-reasoning model tier (per Model Policy: replanning
    is complex reasoning, not a cheap checkpoint).
    """

    def __init__(self, model_provider, max_output_tokens: int = 1500):
        self.model_provider = model_provider
        self.max_output_tokens = max_output_tokens

    def replan(self, request: ReplanRequest) -> TaskPlan:
        plan = request.original_plan
        state = request.execution_state

        first_replaced = min(
            (s.step_id for s in plan.steps if s.step_id not in state.completed_steps),
            default=len(plan.steps),
        )

        completed_desc = _completed_steps_desc(plan, state)
        untouched_desc = "\n".join(
            f"  {s.step_id}. {s.description}"
            for s in plan.steps if s.step_id >= first_replaced
        ) or "  (none)"

        prompt = f"""You are repairing a plan, not restarting it. New evidence has
invalidated an assumption behind the remaining steps. Produce ONLY the
replacement for the remaining (not-yet-executed) portion.

Task: {plan.task_summary}

Completed steps (DO NOT regenerate or repeat these -- they already happened):
{completed_desc}

Untouched steps this replan may change or replace:
{untouched_desc}

Invalidated assumption: {request.invalidated_assumption}
New evidence: {request.new_evidence}

Respond with ONLY a JSON object, no other text:
{{"steps": [
  {{"description": "...", "action_type": "read_file|search_code|list_files|
     analyze_context|think|design|review_findings|write_file|edit_file|
     refactor|run_tests|run_linter|verify|skill_workflow",
    "tool_invocation": {{"tool_name": "...", "arguments": {{}}}} or null,
    "rationale": "...", "depends_on": [], "expected_output": "...",
    "can_fail": false, "can_replan": false}}
]}}

Rules:
- Your first replacement step WILL BE assigned step_id {first_replaced}, your
  second step_id {first_replaced + 1}, and so on in order -- do not include
  "step_id" in your JSON, but DO use those exact final ids in "depends_on".
- depends_on may reference completed step ids ({sorted(state.completed_steps)})
  directly, or your own new steps using the final ids described above
  ({first_replaced}, {first_replaced + 1}, ...). Never use small positional
  indices (0, 1, 2, ...) for depends_on unless that number is itself one of
  the completed step ids or one of your assigned final ids.
- Keep the tail as small as necessary to address the invalidated assumption;
  do not regenerate steps that remain valid."""

        try:
            raw = self.model_provider.call(
                system_prompt="You produce ONLY valid JSON plan repairs. No prose.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=self.max_output_tokens,
            )
        except Exception as e:
            raise ReplanError(f"local replan model call failed: {e}")

        try:
            parsed = _extract_json(raw)
            raw_steps = parsed["steps"]
        except (json.JSONDecodeError, KeyError) as e:
            raise ReplanError(f"local replan returned unparseable response ({e}): {raw!r}")

        # The prompt tells the model its final step_ids up front (starting at
        # first_replaced), so depends_on values in raw_steps are already
        # final ids -- no translation needed here. This sidesteps the
        # ambiguity of positional indices colliding with real completed
        # step_ids (e.g. tail position 0 vs. completed step_id 0).
        try:
            new_tail = dict_list_to_step_tail(raw_steps, first_replaced)
        except PlanParseError as e:
            raise ReplanError(f"local replan produced invalid steps: {e}")

        try:
            return plan.with_replaced_tail(first_replaced, new_tail)
        except ValueError as e:
            raise ReplanError(f"local replan tail rejected: {e}")


class FullReplanner(Replanner):
    """
    Whole-plan reconsideration after final-goal-validation FAIL. Still
    strong-tier. Receives execution_state + prior-attempt history text so it
    doesn't repeat the same mistake (Invariant 10).
    """

    def __init__(self, model_provider, max_output_tokens: int = 2500):
        self.model_provider = model_provider
        self.max_output_tokens = max_output_tokens

    def replan(self, request: ReplanRequest) -> TaskPlan:
        plan = request.original_plan
        state = request.execution_state
        completed_desc = _completed_steps_desc(plan, state)

        prompt = f"""All steps of a plan completed, but the goal was NOT achieved.
Reconsider the task from the beginning. You may reuse findings below, but
you must produce a full, valid replacement plan -- do not assume anything
was pre-executed by whoever runs this plan.

Task: {plan.task_summary}

What was tried and found (useful evidence, not necessarily still relevant):
{completed_desc}

Why the goal validation failed: {request.failure_reason or '(not specified)'}

{request.previous_attempts_summary}

Respond with ONLY a JSON object, no other text:
{{"task_summary": "...", "steps": [ ... same step schema as before ... ],
  "relevant_files": [], "skill_name": null or "..."}}

Rules:
- This is a FULL replacement plan, starting fresh. Your steps will be
  numbered 0, 1, 2, ... sequentially in the exact order you list them --
  do not include "step_id" in your JSON, it is assigned automatically by
  position, starting at 0 (NOT 1).
- Every "depends_on" value MUST refer to one of these final 0-indexed
  positions (the index of another step in YOUR "steps" list, in the order
  you wrote them), never an id from any earlier/previous plan and never
  1-indexed numbering. A step's depends_on values must all be strictly
  less than that step's own position in the list.
- If a step has no dependency, use an empty list: "depends_on": []."""

        try:
            raw = self.model_provider.call(
                system_prompt="You produce ONLY valid JSON task plans. No prose.",
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=self.max_output_tokens,
            )
        except Exception as e:
            raise ReplanError(f"full replan model call failed: {e}")

        try:
            parsed = _extract_json(raw)
        except json.JSONDecodeError as e:
            raise ReplanError(f"full replan returned unparseable response ({e}): {raw!r}")

        try:
            new_plan = dict_to_task_plan(parsed)
        except PlanParseError as e:
            raise ReplanError(f"full replan produced invalid plan: {e}")

        new_plan.parent_plan_id = plan.plan_id
        return new_plan


class MockReplanner(Replanner):
    """For tests. Returns a fixed TaskPlan (or raises a fixed error) regardless of input."""

    def __init__(self, plan: Optional[TaskPlan] = None, error: Optional[Exception] = None):
        self.plan = plan
        self.error = error
        self.calls: list[ReplanRequest] = []

    def replan(self, request: ReplanRequest) -> TaskPlan:
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.plan