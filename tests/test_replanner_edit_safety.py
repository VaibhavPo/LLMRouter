import json
import pytest

from src.core.task_plan import ActionType, TaskStep, TaskPlan, StepStatus, ToolInvocation
from src.core.executor.execution_state import ExecutionState
from src.core.executor.replanner import FullReplanner, ReplanRequest


class FakeModelProvider:
    """Captures the prompt it was called with, returns a canned response."""
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def call(self, system_prompt, user_prompt, temperature=0.1, max_tokens=1024):
        self.last_prompt = user_prompt
        return self.response


def plan_with_completed_read(file_path="abc.html"):
    s0 = TaskStep(
        step_id=0,
        description=f"Read {file_path}",
        action_type=ActionType.READ_FILE,
        tool_invocation=ToolInvocation("read_file", {"file_path": file_path}),
        status=StepStatus.COMPLETED,
        actual_output="<html>...(existing real content)...</html>",
    )
    return TaskPlan(task_summary="add bubble animation to abc.html", steps=[s0])


def test_full_replanner_prompt_contains_edit_safety_rules():
    """The prompt sent to the model must warn against write_file clobbering
    an existing, already-read file."""
    plan = plan_with_completed_read()
    state = ExecutionState(plan_id=plan.plan_id)
    state.record_completed(0)

    fake_response = json.dumps({
        "task_summary": "add bubble animation to abc.html",
        "steps": [
            {"description": "edit abc.html", "action_type": "edit_file",
             "tool_invocation": {"tool_name": "edit_file",
                                  "arguments": {"file_path": "abc.html",
                                                "old_str": "</body>",
                                                "new_str": "<div class='bubble'></div></body>"}},
             "depends_on": []},
        ],
    })
    provider = FakeModelProvider(fake_response)
    replanner = FullReplanner(provider)

    request = ReplanRequest(
        original_plan=plan, execution_state=state,
        invalidated_assumption="", new_evidence="",
        failure_reason="final validation unparseable",
    )
    replanner.replan(request)

    assert "write_file" in provider.last_prompt  # rule text mentions it
    assert "OVERWRITES THE ENTIRE FILE" in provider.last_prompt
    assert "edit_file" in provider.last_prompt


def test_full_replanner_can_still_produce_edit_file_for_existing_file():
    """Sanity check the fix doesn't break normal parsing: a compliant
    edit_file-based plan still parses successfully."""
    plan = plan_with_completed_read()
    state = ExecutionState(plan_id=plan.plan_id)
    state.record_completed(0)

    fake_response = json.dumps({
        "task_summary": "add bubble animation to abc.html",
        "steps": [
            {"description": "edit abc.html to add bubble animation",
             "action_type": "edit_file",
             "tool_invocation": {"tool_name": "edit_file",
                                  "arguments": {"file_path": "abc.html",
                                                "old_str": "</body>",
                                                "new_str": "<div class='bubble'></div></body>"}},
             "depends_on": []},
        ],
    })
    provider = FakeModelProvider(fake_response)
    replanner = FullReplanner(provider)
    request = ReplanRequest(plan, state, "", "", failure_reason="x")

    new_plan = replanner.replan(request)

    assert new_plan.steps[0].action_type == ActionType.EDIT_FILE
    assert new_plan.steps[0].tool_invocation.tool_name == "edit_file"


def test_json_fence_with_python_tag_is_stripped():
    """Regression for the ```python fence bug that made every final
    validation response unparseable."""
    from src.core.executor.replanner import _extract_json

    raw = '```python\n{"outcome": "pass", "reasoning": "ok"}\n```'
    parsed = _extract_json(raw)
    assert parsed == {"outcome": "pass", "reasoning": "ok"}
