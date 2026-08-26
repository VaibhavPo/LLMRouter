# src/core/executor/checkpoint.py
"""
Checkpoint: cheap evaluation of "does the remaining plan still hold?" run
after a step marked can_replan=True completes.

This is deliberately NOT a full replan. It should use the cheap/lightweight
model tier -- the point is that most checkpoints come back VALID and cost
almost nothing, so the system doesn't degrade into think-after-every-step.
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.core.task_plan import TaskStep, TaskPlan
from src.core.executor.execution_state import ExecutionState
from src.core.executor.interfaces import ContextManager
from src.core.plan_serde import strip_code_fence


class CheckpointVerdict(str, Enum):
    VALID = "valid"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"
    UNRECOVERABLE = "unrecoverable"


@dataclass
class CheckpointResult:
    verdict: CheckpointVerdict
    reasoning: str
    invalidated_assumption: Optional[str] = None


class CheckpointError(Exception):
    """Checkpoint evaluator itself failed (model call error, unparseable
    response). This is NOT the same as an INVALID verdict -- it means we
    couldn't get a judgment at all. Callers should treat this the same as
    UNCERTAIN (never silently assume VALID on a checkpoint failure)."""
    pass


class CheckpointEvaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        step: TaskStep,
        plan: TaskPlan,
        context: ContextManager,
        execution_state: ExecutionState,
        deeper: bool = False,
    ) -> CheckpointResult:
        """
        deeper=True is passed on the second call for the same step, after an
        UNCERTAIN verdict, once (see Executor.uncertain_retry_limit) -- an
        implementation may use it to include more context (fuller output,
        an extra tool call) than the cheap first pass.
        """
        ...


def _extract_json(text: str) -> dict:
    return json.loads(strip_code_fence(text))


class ModelCheckpointEvaluator(CheckpointEvaluator):
    """
    Uses a cheap LLMProvider (per Model Policy: checkpoint validation is a
    lightweight-tier task, distinct from planning/replanning's strong tier).
    """

    def __init__(self, model_provider, max_output_preview: int = 300, deeper_preview: int = 2000):
        self.model_provider = model_provider
        self.max_output_preview = max_output_preview
        self.deeper_preview = deeper_preview

    def evaluate(self, step, plan, context, execution_state, deeper: bool = False) -> CheckpointResult:
        preview_len = self.deeper_preview if deeper else self.max_output_preview
        output = context.get_step_output(step.step_id)
        output_preview = output[:preview_len]

        remaining = [
            s for s in plan.steps
            if s.step_id > step.step_id and s.step_id not in execution_state.completed_steps
        ]
        remaining_desc = "\n".join(f"  {s.step_id}. {s.description}" for s in remaining) or "  (none)"

        prompt = f"""A plan step just produced new evidence. Decide whether the remaining
plan still holds, given this evidence.

Completed step {step.step_id}: {step.description}
Evidence produced:
{output_preview}

Remaining plan steps:
{remaining_desc}

Respond with ONLY a JSON object, no other text:
{{"verdict": "valid" | "uncertain" | "invalid" | "unrecoverable",
  "reasoning": "one or two sentences",
  "invalidated_assumption": "what assumption is now wrong, or empty string"}}

- "valid": the evidence is consistent with the remaining plan; proceed as-is.
  IMPORTANT: also respond "valid" (not "uncertain") if you are unsure
  whether an assumption holds, but a remaining plan step already reads,
  searches, or verifies the thing you're unsure about -- that upcoming
  step will surface the problem itself if there is one, so the plan does
  not need to be interrupted now just because you personally can't yet
  confirm it. Only mark something "uncertain" or "invalid" if NO remaining
  step will produce that confirming evidence on its own.
- "invalid": the evidence directly contradicts an assumption behind a
  remaining step (e.g. a file is confirmed to be in a different location
  than a remaining step assumes), AND no remaining step would catch this
  on its own -- the remaining plan needs repair now, not later.
- "uncertain": you cannot tell from this evidence alone, AND no remaining
  step is positioned to resolve that uncertainty on its own.
- "unrecoverable": the evidence shows the task cannot safely continue at all."""

        try:
            raw = self.model_provider.call(
                system_prompt="You are a fast, terse plan-checkpoint evaluator. Output only JSON.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=500,
            )
        except Exception as e:
            raise CheckpointError(f"checkpoint model call failed: {e}")

        if len(raw) > 200 and len(set(raw[-200:])) < 10:
            raise CheckpointError(f"checkpoint model produced degenerate/repetitive output: {raw[:100]!r}...")

        try:
            if not raw or not raw.strip():
                raise CheckpointError("checkpoint model returned an empty response (likely truncated reasoning — increase max_tokens)")
            parsed = _extract_json(raw)
            verdict = CheckpointVerdict(parsed["verdict"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise CheckpointError(f"checkpoint model returned unparseable response ({e}): {raw!r}")

        return CheckpointResult(
            verdict=verdict,
            reasoning=parsed.get("reasoning", ""),
            invalidated_assumption=parsed.get("invalidated_assumption") or None,
        )


class MockCheckpointEvaluator(CheckpointEvaluator):
    """
    For tests. Provide a list of CheckpointResult to return in order (one per
    call to evaluate()), or a dict of {step_id: CheckpointResult} for
    deterministic per-step control regardless of call order.
    """

    def __init__(self, sequence: Optional[list[CheckpointResult]] = None,
                 by_step: Optional[dict[int, CheckpointResult]] = None,
                 default: CheckpointResult = None):
        self.sequence = list(sequence) if sequence else []
        self.by_step = by_step or {}
        self.default = default or CheckpointResult(CheckpointVerdict.VALID, "default mock: valid")
        self.calls: list[tuple] = []

    def evaluate(self, step, plan, context, execution_state, deeper: bool = False) -> CheckpointResult:
        self.calls.append((step.step_id, deeper))
        if step.step_id in self.by_step:
            return self.by_step[step.step_id]
        if self.sequence:
            return self.sequence.pop(0)
        return self.default