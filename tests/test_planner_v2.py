# tests/test_planner_v2.py
"""Test loosely coupled planner."""

import pytest
from src.core.planner_v2.planner import Planner
from src.core.planner_v2.config import PlannerBuilder
from src.core.planner_v2.providers import MockProvider
from src.core.planner_v2.parsers import JSONParser
from src.core.planner_v2.validators import TaskPlanValidator
from src.core.planner_v2.prompts import DefaultPromptBuilder
from src.core.task_plan import PlannerResponse


def test_planner_with_mock_provider():
    """Test that planner works with mock provider."""
    mock_response = '''{
        "task_summary": "test task",
        "steps": [
            {
                "step_id": 0,
                "description": "test step",
                "action_type": "think"
            }
        ]
    }'''
    
    builder = PlannerBuilder()
    planner = builder.build_mock(mock_response)
    
    result = planner.plan(
        user_request="test",
        context_md="test context",
        tool_descriptions={},
    )
    
    assert isinstance(result, PlannerResponse)
    assert len(result.plan.steps) == 1


def test_planner_swappable_components():
    """Test that planner components can be swapped."""
    from src.core.planner_v2.interfaces import Logger
    
    class QuietLogger(Logger):
        def info(self, message: str): pass
        def debug(self, message: str): pass
        def error(self, message: str): pass
    
    builder = PlannerBuilder()
    builder.logger = QuietLogger()  # Swap logger
    
    planner = builder.build_mock()  # Should work with quiet logger
    result = planner.plan("test", "context", {})
    
    assert result is not None


def test_planner_custom_provider():
    """Test creating planner with custom provider."""
    from src.core.planner_v2.interfaces import LLMProvider
    
    class DummyProvider(LLMProvider):
        def call(self, system_prompt, user_prompt, **kwargs):
            return '{"task_summary": "dummy", "steps": [{"step_id": 0, "description": "dummy step", "action_type": "think"}]}'
    
    builder = PlannerBuilder()
    planner = builder.build_custom(
        llm_provider=DummyProvider(),
        prompt_builder=DefaultPromptBuilder(),
    )
    
    result = planner.plan("test", "context", {})
    assert result.plan.task_summary == "dummy"


def test_diagnosis_planner_builder():
    """Test specialized diagnosis planner."""
    builder = PlannerBuilder()
    planner = builder.build_diagnosis()  # Uses DiagnosisPromptBuilder
    
    # Just verify it creates without error
    assert planner is not None


def test_tdd_planner_builder():
    """Test specialized TDD planner."""
    builder = PlannerBuilder()
    planner = builder.build_tdd()  # Uses TDDPromptBuilder
    
    assert planner is not None