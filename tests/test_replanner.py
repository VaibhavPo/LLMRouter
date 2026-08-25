import json
import pytest

from src.core.task_plan import ActionType, TaskStep, TaskPlan, StepStatus, ToolInvocation
from src.core.executor.execution_state import ExecutionState
from src.core.executor.replanner import (
    LocalReplanner, FullReplanner, ReplanRequest, ReplanError, MockReplanner,
)


class FakeModelProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, system_prompt, user_prompt, temperature=0.1, max_tokens=1024):
        self.calls.append((system_prompt, user_prompt, temperature, max_tokens))
        return self.responses.pop(0)


def base_plan():
    s0 = TaskStep(step_id=0, description="read forms.py", action_type=ActionType.READ_FILE,
                  tool_invocation=ToolInvocation("read_file", {"file_path": "forms.py"}),
                  status=StepStatus.COMPLETED, actual_output="not here")
    s1 = TaskStep(step_id=1, description="search for form class", action_type=ActionType.SEARCH_CODE,
                  tool_invocation=ToolInvocation("search_code", {"pattern": "class Form"}),
                  status=StepStatus.COMPLETED, actual_output="found in registration/form.py",
                  depends_on=[0])
    s2 = TaskStep(step_id=2, description="edit forms.py", action_type=ActionType.EDIT_FILE,
                  tool_invocation=ToolInvocation("edit_file", {"file_path": "forms.py"}),
                  depends_on=[1])
    s3 = TaskStep(step_id=3, description="run tests", action_type=ActionType.RUN_TESTS,
                  tool_invocation=ToolInvocation("run_tests", {}), depends_on=[2])
    return TaskPlan(task_summary="add validation", steps=[s0, s1, s2, s3])


def make_state(plan, completed):
    state = ExecutionState(plan_id=plan.plan_id)
    for sid in completed:
        state.record_completed(sid, plan.steps[sid].actual_output)
    return state


def test_local_replanner_produces_new_tail_and_preserves_prefix():
    response = json.dumps({"steps": [
        {"description": "edit registration/form.py",
         "action_type": "edit_file",
         "tool_invocation": {"tool_name": "edit_file", "arguments": {"file_path": "registration/form.py"}},
         "depends_on": [], "can_fail": False, "can_replan": False},
        {"description": "run tests",
         "action_type": "run_tests",
         "tool_invocation": {"tool_name": "run_tests", "arguments": {}},
         "depends_on": [2], "can_fail": False, "can_replan": False},
    ]})
    provider = FakeModelProvider([response])
    replanner = LocalReplanner(provider)

    plan = base_plan()
    state = make_state(plan, completed=[0, 1])
    request = ReplanRequest(
        original_plan=plan, execution_state=state,
        invalidated_assumption="forms.py location", new_evidence="found in registration/form.py",
    )

    new_plan = replanner.replan(request)

    # completed prefix untouched
    assert new_plan.steps[0] is plan.steps[0]
    assert new_plan.steps[1] is plan.steps[1]
    # tail replaced and renumbered starting at 2
    assert new_plan.steps[2].step_id == 2
    assert new_plan.steps[2].tool_invocation.arguments["file_path"] == "registration/form.py"
    assert new_plan.steps[3].step_id == 3
    assert new_plan.steps[3].depends_on == [2]  # model used the final id it was told to use
    assert new_plan.parent_plan_id == plan.plan_id


def test_local_replanner_tail_can_depend_on_completed_step():
    response = json.dumps({"steps": [
        {"description": "edit registration/form.py", "action_type": "edit_file",
         "tool_invocation": {"tool_name": "edit_file", "arguments": {}},
         "depends_on": [1], "can_fail": False},  # depends on completed step 1 directly
    ]})
    provider = FakeModelProvider([response])
    replanner = LocalReplanner(provider)

    plan = base_plan()
    state = make_state(plan, completed=[0, 1])
    request = ReplanRequest(plan, state, "assumption", "evidence")

    new_plan = replanner.replan(request)
    assert new_plan.steps[2].depends_on == [1]


def test_local_replanner_raises_on_unparseable_json():
    provider = FakeModelProvider(["not json"])
    replanner = LocalReplanner(provider)
    plan = base_plan()
    state = make_state(plan, completed=[0, 1])
    request = ReplanRequest(plan, state, "a", "e")

    with pytest.raises(ReplanError):
        replanner.replan(request)


def test_local_replanner_raises_on_bad_action_type():
    response = json.dumps({"steps": [
        {"description": "do a thing", "action_type": "fly_to_the_moon", "depends_on": []}
    ]})
    provider = FakeModelProvider([response])
    replanner = LocalReplanner(provider)
    plan = base_plan()
    state = make_state(plan, completed=[0, 1])
    request = ReplanRequest(plan, state, "a", "e")

    with pytest.raises(ReplanError):
        replanner.replan(request)


def test_local_replanner_wraps_model_call_exception():
    class ExplodingProvider:
        def call(self, **kwargs):
            raise RuntimeError("model server down")

    replanner = LocalReplanner(ExplodingProvider())
    plan = base_plan()
    state = make_state(plan, completed=[0, 1])
    request = ReplanRequest(plan, state, "a", "e")

    with pytest.raises(ReplanError, match="model server down"):
        replanner.replan(request)


def test_full_replanner_produces_fresh_plan_with_parent_lineage():
    response = json.dumps({
        "task_summary": "add validation (retry)",
        "steps": [
            {"description": "read UserSchema", "action_type": "read_file",
             "tool_invocation": {"tool_name": "read_file", "arguments": {"file_path": "user.py"}},
             "depends_on": []},
        ],
    })
    provider = FakeModelProvider([response])
    replanner = FullReplanner(provider)

    plan = base_plan()
    state = make_state(plan, completed=[0, 1, 2, 3])
    request = ReplanRequest(plan, state, "", "", failure_reason="tests still fail")

    new_plan = replanner.replan(request)
    assert new_plan.task_summary == "add validation (retry)"
    assert new_plan.parent_plan_id == plan.plan_id
    assert new_plan.plan_id != plan.plan_id  # full replan is a new lineage


def test_mock_replanner_records_requests():
    plan = base_plan()
    mock = MockReplanner(plan=plan)
    state = make_state(plan, completed=[0])
    request = ReplanRequest(plan, state, "a", "e")

    result = mock.replan(request)
    assert result is plan
    assert mock.calls == [request]


def test_mock_replanner_can_raise():
    mock = MockReplanner(error=ReplanError("boom"))
    plan = base_plan()
    state = make_state(plan, completed=[0])
    with pytest.raises(ReplanError, match="boom"):
        mock.replan(ReplanRequest(plan, state, "a", "e"))