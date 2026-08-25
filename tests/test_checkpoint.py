import json
import pytest

from src.core.task_plan import ActionType, TaskStep, TaskPlan, StepStatus, ToolInvocation
from src.core.executor.context_manager import PlanExecutionContext
from src.core.executor.execution_state import ExecutionState
from src.core.executor.checkpoint import (
    ModelCheckpointEvaluator,
    MockCheckpointEvaluator,
    CheckpointVerdict,
    CheckpointResult,
    CheckpointError,
)


class FakeModelProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, system_prompt, user_prompt, temperature=0.1, max_tokens=1024):
        self.calls.append((system_prompt, user_prompt, temperature, max_tokens))
        return self.responses.pop(0)


def make_plan_with_evidence_step():
    s0 = TaskStep(step_id=0, description="read forms.py", action_type=ActionType.READ_FILE,
                  tool_invocation=ToolInvocation("read_file", {"file_path": "forms.py"}),
                  can_replan=True, status=StepStatus.COMPLETED, actual_output="class Form: ...")
    s1 = TaskStep(step_id=1, description="edit forms.py", action_type=ActionType.EDIT_FILE,
                  tool_invocation=ToolInvocation("edit_file", {"file_path": "forms.py"}),
                  depends_on=[0])
    return TaskPlan(task_summary="edit form", steps=[s0, s1])


def test_model_checkpoint_evaluator_parses_valid():
    provider = FakeModelProvider([
        json.dumps({"verdict": "valid", "reasoning": "matches", "invalidated_assumption": ""})
    ])
    evaluator = ModelCheckpointEvaluator(provider)
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    ctx.set_step_output(0, "class Form: ...")
    state = ExecutionState(plan_id=plan.plan_id)

    result = evaluator.evaluate(plan.steps[0], plan, ctx, state)
    assert result.verdict == CheckpointVerdict.VALID
    assert result.invalidated_assumption is None


def test_model_checkpoint_evaluator_strips_code_fence():
    provider = FakeModelProvider([
        "```json\n" + json.dumps({"verdict": "invalid", "reasoning": "moved",
                                   "invalidated_assumption": "forms.py location"}) + "\n```"
    ])
    evaluator = ModelCheckpointEvaluator(provider)
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    ctx.set_step_output(0, "class Form: ...")
    state = ExecutionState(plan_id=plan.plan_id)

    result = evaluator.evaluate(plan.steps[0], plan, ctx, state)
    assert result.verdict == CheckpointVerdict.INVALID
    assert result.invalidated_assumption == "forms.py location"


def test_model_checkpoint_evaluator_raises_checkpoint_error_on_bad_json():
    provider = FakeModelProvider(["not json at all"])
    evaluator = ModelCheckpointEvaluator(provider)
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    ctx.set_step_output(0, "x")
    state = ExecutionState(plan_id=plan.plan_id)

    with pytest.raises(CheckpointError):
        evaluator.evaluate(plan.steps[0], plan, ctx, state)


def test_model_checkpoint_evaluator_raises_checkpoint_error_on_bad_verdict():
    provider = FakeModelProvider([json.dumps({"verdict": "maybe", "reasoning": "?"})])
    evaluator = ModelCheckpointEvaluator(provider)
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    ctx.set_step_output(0, "x")
    state = ExecutionState(plan_id=plan.plan_id)

    with pytest.raises(CheckpointError):
        evaluator.evaluate(plan.steps[0], plan, ctx, state)


def test_model_checkpoint_evaluator_uses_deeper_preview_when_deeper():
    long_output = "x" * 5000
    provider = FakeModelProvider([
        json.dumps({"verdict": "valid", "reasoning": "ok"}),
    ])
    evaluator = ModelCheckpointEvaluator(provider, max_output_preview=50, deeper_preview=4000)
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    ctx.set_step_output(0, long_output)
    state = ExecutionState(plan_id=plan.plan_id)

    evaluator.evaluate(plan.steps[0], plan, ctx, state, deeper=True)
    _, user_prompt, _, _ = provider.calls[0]
    assert len(user_prompt) > 3000  # deeper preview included far more of the output


def test_mock_checkpoint_evaluator_by_step():
    mock = MockCheckpointEvaluator(by_step={
        0: CheckpointResult(CheckpointVerdict.INVALID, "moved", "location"),
    })
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    state = ExecutionState(plan_id=plan.plan_id)

    result = mock.evaluate(plan.steps[0], plan, ctx, state)
    assert result.verdict == CheckpointVerdict.INVALID
    assert mock.calls == [(0, False)]


def test_mock_checkpoint_evaluator_default_is_valid():
    mock = MockCheckpointEvaluator()
    plan = make_plan_with_evidence_step()
    ctx = PlanExecutionContext()
    state = ExecutionState(plan_id=plan.plan_id)

    result = mock.evaluate(plan.steps[0], plan, ctx, state)
    assert result.verdict == CheckpointVerdict.VALID