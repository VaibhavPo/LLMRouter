# src/core/planner_v2/config.py
"""Configuration."""
# src/core/planner_v2/config.py
"""
Configuration and factory for Planner.
Responsible for wiring all components together.
"""

from .planner import Planner
from .providers import LMStudioProvider, MockProvider
from .parsers import JSONParser
from .validators import TaskPlanValidator
from .prompts import DefaultPromptBuilder, DiagnosisPromptBuilder, TDDPromptBuilder
from .interfaces import Logger
from src.core.task_plan import TaskPlan, TaskStep, ActionType, ToolInvocation
from src.core.model_tiers import ModelTier, resolve_tier
from typing import Optional


class ConsoleLogger(Logger):
    """Simple console logger."""

    def info(self, message: str):
        print(message)

    def debug(self, message: str):
        print(f"[DEBUG] {message}")

    def error(self, message: str):
        print(f"[ERROR] {message}")


class TaskPlanFactory:
    """Factory for creating TaskPlan objects from dicts."""

    def create(self, plan_dict: dict) -> TaskPlan:
        """Convert validated dict to TaskPlan."""
        steps = []

        for step_json in plan_dict.get("steps", []):
            tool_inv = None
            if "tool_invocation" in step_json:
                tool_inv_json = step_json["tool_invocation"]
                tool_inv = ToolInvocation(
                    tool_name=tool_inv_json["tool_name"],
                    arguments=tool_inv_json.get("arguments", {})
                )

            # LLM JSON output is inconsistent about int vs string for
            # numeric fields (e.g. depends_on: ["0"] instead of [0]).
            # Coerce here, at the untrusted-JSON boundary, so every
            # downstream dataclass can assume real ints.
            raw_depends_on = step_json.get("depends_on", [])
            depends_on = [int(d) for d in raw_depends_on]

            step = TaskStep(
                step_id=int(step_json["step_id"]),
                description=step_json["description"],
                action_type=ActionType(step_json["action_type"]),
                tool_invocation=tool_inv,
                rationale=step_json.get("rationale", ""),
                depends_on=depends_on,
                expected_output=step_json.get("expected_output", ""),
                estimated_time_seconds=int(step_json.get("estimated_time_seconds", 0)),
                # BUGFIX: these three were previously never read from
                # step_json at all, so every step from an INITIAL plan
                # silently got can_fail=False/can_replan=False regardless
                # of what the LLM actually specified -- meaning the
                # checkpoint/local-replan loop could never fire on a
                # first-pass plan, only on already-replanned tails (which
                # go through plan_serde.dict_to_task_step, which already
                # read these correctly). Matches plan_serde.py's field
                # handling now.
                can_fail=step_json.get("can_fail", False),
                failure_mode=step_json.get("failure_mode", ""),
                can_replan=step_json.get("can_replan", False),
            )
            steps.append(step)

        plan = TaskPlan(
            task_summary=plan_dict["task_summary"],
            steps=steps,
            relevant_files=plan_dict.get("relevant_files", []),
            skill_name=plan_dict.get("skill_name"),
        )

        return plan

class PlannerBuilder:
    """
    Builder for creating configured Planner instances.

    Planning is a HIGH_REASONING-tier role (per the intended
    architecture: Planner / Replanner / FinalValidator all need strong
    reasoning, Checkpoint gets MID_REASONING, deterministic tools need
    no model at all). build_default/build_diagnosis/build_tdd now
    resolve HIGH_REASONING via model_tiers.py instead of each
    independently hardcoding "google/gemma-4-e2b" as a default arg —
    that duplication was the root cause of "everything routes to
    gemma" even after gateway.py's _MODEL_REGISTRY was set up with
    other models, since planner_v2 never consulted it.

    model_id is still accepted as an explicit override for callers that
    need to pin a specific model (e.g. a benchmark run comparing models
    for the same role) — passing it bypasses tier resolution entirely.
    """

    def __init__(self):
        self.logger = ConsoleLogger()
        self.factory = TaskPlanFactory()

    def _resolve_planning_model_id(self, model_id: Optional[str]) -> str:
        if model_id is not None:
            return model_id
        return resolve_tier(ModelTier.HIGH_REASONING)

    def build_default(self, model_id: str = None) -> Planner:
        """Build a Planner with default settings (LM Studio + default prompts)."""
        return Planner(
            llm_provider=LMStudioProvider(self._resolve_planning_model_id(model_id)),
            prompt_builder=DefaultPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )

    def build_diagnosis(self, model_id: str = None) -> Planner:
        """Build a Planner specialized for diagnosis tasks."""
        return Planner(
            llm_provider=LMStudioProvider(self._resolve_planning_model_id(model_id)),
            prompt_builder=DiagnosisPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )

    def build_tdd(self, model_id: str = None) -> Planner:
        """Build a Planner specialized for TDD tasks."""
        return Planner(
            llm_provider=LMStudioProvider(self._resolve_planning_model_id(model_id)),
            prompt_builder=TDDPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )

    def build_mock(self, mock_response: str = None) -> Planner:
        """Build a Planner with mock LLM (for testing)."""
        if mock_response is None:
            mock_response = '{"task_summary": "mock plan", "steps": [{"step_id": 0, "description": "mock step", "action_type": "think"}]}'

        return Planner(
            llm_provider=MockProvider(mock_response),
            prompt_builder=DefaultPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )

    def build_custom(
        self,
        llm_provider,
        prompt_builder,
        parser=None,
        validator=None,
    ) -> Planner:
        """Build a Planner with custom components."""
        return Planner(
            llm_provider=llm_provider,
            prompt_builder=prompt_builder,
            parser=parser or JSONParser(),
            validator=validator or TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )