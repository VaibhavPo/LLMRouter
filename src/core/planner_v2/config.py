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
            # Parse tool invocation if present
            tool_inv = None
            if "tool_invocation" in step_json:
                tool_inv_json = step_json["tool_invocation"]
                tool_inv = ToolInvocation(
                    tool_name=tool_inv_json["tool_name"],
                    arguments=tool_inv_json.get("arguments", {})
                )
            
            step = TaskStep(
                step_id=step_json["step_id"],
                description=step_json["description"],
                action_type=ActionType(step_json["action_type"]),
                tool_invocation=tool_inv,
                rationale=step_json.get("rationale", ""),
                depends_on=step_json.get("depends_on", []),
                expected_output=step_json.get("expected_output", ""),
                estimated_time_seconds=step_json.get("estimated_time_seconds", 0),
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
    """Builder for creating configured Planner instances."""
    
    def __init__(self):
        self.logger = ConsoleLogger()
        self.factory = TaskPlanFactory()
    
    def build_default(self, model_id: str = "octopus-planning") -> Planner:
        """Build a Planner with default settings (LM Studio + default prompts)."""
        return Planner(
            llm_provider=LMStudioProvider(model_id),
            prompt_builder=DefaultPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )
    
    def build_diagnosis(self, model_id: str = "octopus-planning") -> Planner:
        """Build a Planner specialized for diagnosis tasks."""
        return Planner(
            llm_provider=LMStudioProvider(model_id),
            prompt_builder=DiagnosisPromptBuilder(),
            parser=JSONParser(),
            validator=TaskPlanValidator(),
            plan_factory=self.factory,
            logger=self.logger,
        )
    
    def build_tdd(self, model_id: str = "octopus-planning") -> Planner:
        """Build a Planner specialized for TDD tasks."""
        return Planner(
            llm_provider=LMStudioProvider(model_id),
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