import pytest
from src.core.task_plan import ActionType, StepStatus, TaskStep, TaskPlan, ToolInvocation


def make_step(step_id, action_type=ActionType.THINK, depends_on=None, can_replan=False,
              status=StepStatus.PENDING, tool=None, actual_output=None):
    return TaskStep(
        step_id=step_id,
        description=f"step {step_id}",
        action_type=action_type,
        tool_invocation=tool,
        depends_on=depends_on or [],
        can_replan=can_replan,
        status=status,
        actual_output=actual_output,
    )


def test_can_replan_defaults_false():
    step = make_step(0)
    assert step.can_replan is False


def test_plan_has_plan_id_and_no_parent_by_default():
    plan = TaskPlan(task_summary="t", steps=[make_step(0)])
    assert plan.plan_id
    assert plan.parent_plan_id is None


def test_with_replaced_tail_preserves_completed_prefix():
    s0 = make_step(0, status=StepStatus.COMPLETED, actual_output="file contents")
    s1 = make_step(1, status=StepStatus.COMPLETED, actual_output="found pattern", depends_on=[0])
    s2 = make_step(2, status=StepStatus.PENDING, depends_on=[1])
    plan = TaskPlan(task_summary="t", steps=[s0, s1, s2])

    new_tail = [make_step(2, depends_on=[1])]
    new_plan = plan.with_replaced_tail(2, new_tail)

    assert new_plan.steps[0] is s0
    assert new_plan.steps[1] is s1
    assert new_plan.steps[0].status == StepStatus.COMPLETED
    assert new_plan.steps[0].actual_output == "file contents"
    assert new_plan.steps[2] is new_tail[0]
    assert new_plan.parent_plan_id == plan.plan_id
    assert new_plan.plan_id == plan.plan_id  # same lineage for a local repair


def test_with_replaced_tail_rejects_incomplete_prefix():
    s0 = make_step(0, status=StepStatus.PENDING)  # not actually done
    s1 = make_step(1, depends_on=[0])
    plan = TaskPlan(task_summary="t", steps=[s0, s1])

    with pytest.raises(ValueError, match="not complete"):
        plan.with_replaced_tail(1, [make_step(1)])


def test_with_replaced_tail_rejects_wrong_numbering():
    s0 = make_step(0, status=StepStatus.COMPLETED, actual_output="x")
    plan = TaskPlan(task_summary="t", steps=[s0, make_step(1)])

    wrong = [make_step(5)]  # should have been numbered 1
    with pytest.raises(ValueError, match="numbered sequentially"):
        plan.with_replaced_tail(1, wrong)


def test_with_replaced_tail_can_grow_the_tail():
    s0 = make_step(0, status=StepStatus.COMPLETED, actual_output="x")
    plan = TaskPlan(task_summary="t", steps=[s0, make_step(1)])

    grown_tail = [make_step(1), make_step(2, depends_on=[1]), make_step(3, depends_on=[2])]
    new_plan = plan.with_replaced_tail(1, grown_tail)

    assert len(new_plan.steps) == 4
    assert new_plan.topological_order() == [0, 1, 2, 3]


def test_with_replaced_tail_rejects_forward_dependency_in_tail():
    s0 = make_step(0, status=StepStatus.COMPLETED, actual_output="x")
    plan = TaskPlan(task_summary="t", steps=[s0, make_step(1)])

    # TaskStep.__post_init__ rejects step depending on itself/later at
    # construction time already, so we can't even build this bad tail --
    # this documents that the validation is enforced at the TaskStep layer.
    with pytest.raises(ValueError):
        make_step(1, depends_on=[1])