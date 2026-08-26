# src/core/executor/final_validation.py
"""
Final goal validation: completion of all planned steps is NOT task success.

Runs once, after ALL_STEPS_COMPLETE, before the Executor is allowed to
report SUCCESS. FAIL triggers a full replan (Section 20-21), not a local
one -- the entire strategy may have been insufficient.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.core.task_plan import TaskPlan
from src.core.executor.execution_state import ExecutionState


class FinalOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass
class FinalValidationResult:
    outcome: FinalOutcome
    reasoning: str = ""


class FinalValidator(ABC):
    @abstractmethod
    def validate(self, plan: TaskPlan, execution_state: ExecutionState, context) -> FinalValidationResult:
        ...


class NoopFinalValidator(FinalValidator):
    """Default when the caller hasn't wired a real one. Always PASS.

    This exists so Executor is usable without final validation configured
    (matching the old Phase 7d behavior), but it is a deliberate opt-out --
    Invariant 7 ("never declare success solely because every step returned
    success") is only actually honored once a real validator is wired in.
    """

    def validate(self, plan, execution_state, context) -> FinalValidationResult:
        return FinalValidationResult(FinalOutcome.PASS, "no final validator configured")


class ModelFinalValidator(FinalValidator):
    """Uses the strong model tier -- same as planning/full-replan."""

    def __init__(self, model_provider, acceptance_criteria: str = ""):
        self.model_provider = model_provider
        self.acceptance_criteria = acceptance_criteria

    def validate(self, plan: TaskPlan, execution_state: ExecutionState, context) -> FinalValidationResult:
        import json
        import re

        evidence_lines = []
        for step in plan.steps:
            if step.step_id in execution_state.completed_steps:
                output = context.get_step_output(step.step_id)
                evidence_lines.append(f"- {step.description}: {output[:300]}")
        evidence = "\n".join(evidence_lines) or "(no completed steps)"

        prompt = f"""Does the actual resulting state satisfy the original goal?

Goal: {plan.task_summary}
Acceptance criteria: {self.acceptance_criteria or '(none specified -- use the goal itself)'}

Evidence from execution:
{evidence}

Respond with ONLY JSON: {{"outcome": "pass" | "fail", "reasoning": "..."}}"""

        # BUGFIX: this method previously had no error handling at all --
        # a model call failure, an empty response, or unparseable JSON
        # (e.g. json.loads("") -> "Expecting value: line 1 column 1
        # (char 0)") propagated straight up through Executor.execute(),
        # which has no try/except around final_validator.validate(),
        # crashing the entire CLI process instead of the run failing
        # gracefully. Per Invariant 7 ("never declare success solely
        # because every step returned success"), an errored validator
        # must NOT be treated as an implicit PASS -- but it also should
        # never crash the process. Treating it as FAIL is the correct
        # conservative choice: FAIL triggers FullReplanner (or a plain
        # reported failure if none is configured / replan limit is hit),
        # which is exactly the existing, already-tested path for "the
        # goal wasn't confirmed met." This mirrors how CheckpointError is
        # already handled in checkpoint.py's evaluate() callers -- never
        # silently assume the good outcome on evaluator failure.
        try:
            raw = self.model_provider.call(
                system_prompt="You are a strict goal-completion judge. Output only JSON.",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=300,
            )
        except Exception as e:
            return FinalValidationResult(
                FinalOutcome.FAIL,
                f"final validation model call failed, treating as not-yet-confirmed: {e}",
            )

        try:
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
            if not cleaned:
                raise ValueError("model returned an empty response")
            parsed = json.loads(cleaned)
            outcome = FinalOutcome(parsed["outcome"])
            reasoning = parsed.get("reasoning", "")
        except Exception as e:
            return FinalValidationResult(
                FinalOutcome.FAIL,
                f"final validation response was unparseable, treating as "
                f"not-yet-confirmed ({e}): {raw[:300]!r}",
            )

        return FinalValidationResult(outcome, reasoning)


class MockFinalValidator(FinalValidator):
    """For tests. Returns a fixed queue of results, one per call."""

    def __init__(self, results: Optional[list[FinalValidationResult]] = None,
                 default: FinalValidationResult = None):
        self.results = list(results) if results else []
        self.default = default or FinalValidationResult(FinalOutcome.PASS, "default mock: pass")
        self.calls = 0

    def validate(self, plan, execution_state, context) -> FinalValidationResult:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return self.default