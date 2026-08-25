import tempfile

import pytest

from src.core.task_plan import ActionType, TaskStep, TaskPlan, StepStatus, ToolInvocation
from src.core.executor.context_manager import PlanExecutionContext
from src.core.executor.executor import Executor, ExecutorConfig, SilentLogger
from src.core.executor.interfaces import StepExecutor, StepExecutorFactory, StepExecutionError
from src.core.executor.checkpoint import MockCheckpointEvaluator, CheckpointResult, CheckpointVerdict
from src.core.executor.replanner import MockReplanner, ReplanError
from src.core.executor.final_validation import MockFinalValidator, FinalValidationResult, FinalOutcome
from src.core.executor.execution_history import ExecutionHistoryStore


class ScriptedStepExecutor(StepExecutor):
    """Returns canned output per step_id, or raises for scripted failures."""

    def __init__(self, outputs=None, failures=None):
        self.outputs = outputs or {}
        self.failures = failures or {}
        self.calls = []

    def execute(self, step, plan, context):
        self.calls.append(step.step_id)
        if step.step_id in self.failures:
            raise StepExecutionError(self.failures[step.step_id])
        return self.outputs.get(step.step_id, f"output-{step.step_id}")


class ScriptedFactory(StepExecutorFactory):
    def __init__(self, step_executor):
        self.step_executor = step_executor

    def create(self, action_type):
        return self.step_executor


def step(step_id, depends_on=None, can_replan=False, can_fail=False,
         action_type=ActionType.THINK):
    return TaskStep(
        step_id=step_id,
        description=f"step {step_id}",
        action_type=action_type,
        depends_on=depends_on or [],
        can_replan=can_replan,
        can_fail=can_fail,
    )


def build_executor(step_executor, checkpoint_evaluator=None, local_replanner=None,
                    full_replanner=None, final_validator=None, history_store=None,
                    config=None):
    return Executor(
        step_executor_factory=ScriptedFactory(step_executor),
        context_manager=PlanExecutionContext(),
        logger=SilentLogger(),
        checkpoint_evaluator=checkpoint_evaluator or MockCheckpointEvaluator(),
        local_replanner=local_replanner or MockReplanner(),
        full_replanner=full_replanner,
        final_validator=final_validator,
        history_store=history_store,
        config=config or ExecutorConfig(),
    )


# -- VALID path: cheap, no replanning ---------------------------------------

def test_normal_plan_all_checkpoints_valid_no_replanning():
    plan = TaskPlan(task_summary="t", steps=[
        step(0, can_replan=True),
        step(1, depends_on=[0]),
        step(2, depends_on=[1]),
    ])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator()  # default VALID
    replanner = MockReplanner()  # should never be called

    executor = build_executor(se, checkpoint_evaluator=checkpoint, local_replanner=replanner)
    result = executor.execute(plan, task_id="t1", original_task="do the thing")

    assert result.final_outcome == "success"
    assert result.completed_steps == {0, 1, 2}
    assert se.calls == [0, 1, 2]
    assert replanner.calls == []  # no unnecessary replanning


# -- INVALID path: local replan repairs the tail -----------------------------

def test_invalid_checkpoint_triggers_local_replan_and_preserves_completed_work():
    plan = TaskPlan(task_summary="t", steps=[
        step(0, can_replan=True),
        step(1, depends_on=[0]),
    ])
    se = ScriptedStepExecutor(outputs={0: "forms.py not found here"})
    checkpoint = MockCheckpointEvaluator(by_step={
        0: CheckpointResult(CheckpointVerdict.INVALID, "moved", "forms.py location"),
    })

    def build_repaired_plan(request):
        repaired_step1 = step(1, depends_on=[0])
        repaired_step1.description = "edit registration/form.py"
        return request.original_plan.with_replaced_tail(1, [repaired_step1])

    class RepairingReplanner(MockReplanner):
        def replan(self, request):
            self.calls.append(request)
            return build_repaired_plan(request)

    replanner = RepairingReplanner()
    executor = build_executor(se, checkpoint_evaluator=checkpoint, local_replanner=replanner)
    result = executor.execute(plan, task_id="t2", original_task="edit form")

    assert result.final_outcome == "success"
    assert result.completed_steps == {0, 1}
    assert result.replan_count == 1
    assert len(replanner.calls) == 1
    # completed step 0's output is untouched by the replan
    assert result.context_snapshot[0] == "forms.py not found here"


# -- UNCERTAIN path: retried once, then escalated ----------------------------

def test_uncertain_checkpoint_retries_once_then_resolves_valid():
    plan = TaskPlan(task_summary="t", steps=[step(0, can_replan=True), step(1, depends_on=[0])])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(sequence=[
        CheckpointResult(CheckpointVerdict.UNCERTAIN, "not sure"),
        CheckpointResult(CheckpointVerdict.VALID, "actually fine on closer look"),
    ])
    replanner = MockReplanner()

    executor = build_executor(se, checkpoint_evaluator=checkpoint, local_replanner=replanner,
                               config=ExecutorConfig(uncertain_retry_limit=1))
    result = executor.execute(plan, task_id="t3", original_task="x")

    assert result.final_outcome == "success"
    assert checkpoint.calls == [(0, False), (0, True)]
    assert replanner.calls == []


def test_uncertain_checkpoint_escalates_to_local_replan_after_retry_limit():
    plan = TaskPlan(task_summary="t", steps=[step(0, can_replan=True), step(1, depends_on=[0])])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(sequence=[
        CheckpointResult(CheckpointVerdict.UNCERTAIN, "not sure"),
        CheckpointResult(CheckpointVerdict.UNCERTAIN, "still not sure"),
    ])

    class RepairingReplanner(MockReplanner):
        def replan(self, request):
            self.calls.append(request)
            return request.original_plan.with_replaced_tail(1, [step(1, depends_on=[0])])

    replanner = RepairingReplanner()
    executor = build_executor(se, checkpoint_evaluator=checkpoint, local_replanner=replanner,
                               config=ExecutorConfig(uncertain_retry_limit=1))

    result = executor.execute(plan, task_id="t4", original_task="x")

    assert len(replanner.calls) == 1
    assert result.replan_count == 1


# -- UNRECOVERABLE path: abort and persist -----------------------------------

def test_unrecoverable_checkpoint_aborts_without_replanning():
    plan = TaskPlan(task_summary="t", steps=[step(0, can_replan=True), step(1, depends_on=[0])])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(by_step={
        0: CheckpointResult(CheckpointVerdict.UNRECOVERABLE, "environment is broken"),
    })
    replanner = MockReplanner()

    with tempfile.TemporaryDirectory() as d:
        history = ExecutionHistoryStore(d)
        executor = build_executor(se, checkpoint_evaluator=checkpoint,
                                   local_replanner=replanner, history_store=history)
        result = executor.execute(plan, task_id="t5", original_task="x")

        assert result.final_outcome == "aborted"
        assert replanner.calls == []
        assert se.calls == [0]  # step 1 never ran

        attempts = history.get_attempts("t5")
        assert attempts[0].final_outcome == "aborted"
        assert "environment is broken" in attempts[0].failure_reason


# -- replan limit ------------------------------------------------------------

def test_replan_limit_reached_aborts_cleanly():
    # Checkpoint always says INVALID and the "repair" just resubmits an
    # equivalent single-step plan, so it keeps tripping the checkpoint --
    # this should hit the replan limit rather than loop forever.
    plan = TaskPlan(task_summary="t", steps=[step(0, can_replan=True)])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(default=CheckpointResult(CheckpointVerdict.INVALID, "always wrong"))

    class StubbornReplanner(MockReplanner):
        def replan(self, request):
            self.calls.append(request)
            new_step0 = step(0, can_replan=True)
            new_step0.status = StepStatus.PENDING
            return request.original_plan.with_replaced_tail(0, [new_step0])

    replanner = StubbornReplanner()
    executor = build_executor(se, checkpoint_evaluator=checkpoint, local_replanner=replanner,
                               config=ExecutorConfig(max_replans=2))
    result = executor.execute(plan, task_id="t6", original_task="x")

    assert result.final_outcome == "aborted"
    assert result.replan_count == 2
    assert "replan limit" in result.failure_reason


def test_replan_error_aborts_and_is_persisted():
    plan = TaskPlan(task_summary="t", steps=[step(0, can_replan=True)])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(default=CheckpointResult(CheckpointVerdict.INVALID, "wrong"))
    replanner = MockReplanner(error=ReplanError("model unreachable"))

    with tempfile.TemporaryDirectory() as d:
        history = ExecutionHistoryStore(d)
        executor = build_executor(se, checkpoint_evaluator=checkpoint,
                                   local_replanner=replanner, history_store=history)
        result = executor.execute(plan, task_id="t7", original_task="x")

    assert result.final_outcome == "aborted"
    assert "model unreachable" in result.failure_reason


# -- final validation FAIL -> full replan ------------------------------------

def test_final_validation_fail_triggers_full_replan_then_succeeds():
    plan = TaskPlan(task_summary="t", steps=[step(0)])
    se = ScriptedStepExecutor()

    better_plan = TaskPlan(task_summary="t (retry)", steps=[step(0)], parent_plan_id=plan.plan_id)
    full_replanner = MockReplanner(plan=better_plan)

    final_validator = MockFinalValidator(results=[
        FinalValidationResult(FinalOutcome.FAIL, "goal not actually met"),
        FinalValidationResult(FinalOutcome.PASS, "now it is"),
    ])

    executor = build_executor(se, full_replanner=full_replanner, final_validator=final_validator)
    result = executor.execute(plan, task_id="t8", original_task="x")

    assert result.final_outcome == "success"
    assert result.replan_count == 1
    assert len(full_replanner.calls) == 1
    assert final_validator.calls == 2


def test_final_validation_fail_without_full_replanner_reports_failure():
    plan = TaskPlan(task_summary="t", steps=[step(0)])
    se = ScriptedStepExecutor()
    final_validator = MockFinalValidator(default=FinalValidationResult(FinalOutcome.FAIL, "nope"))

    executor = build_executor(se, full_replanner=None, final_validator=final_validator)
    result = executor.execute(plan, task_id="t9", original_task="x")

    assert result.final_outcome == "failure"
    assert "nope" in result.failure_reason


# -- plain step failure (no checkpoint involved) -----------------------------

def test_step_failure_with_can_fail_is_skipped_not_aborted():
    plan = TaskPlan(task_summary="t", steps=[
        step(0, can_fail=True), step(1, depends_on=[]),
    ])
    se = ScriptedStepExecutor(failures={0: "transient tool error"})

    executor = build_executor(se)
    result = executor.execute(plan, task_id="t10", original_task="x")

    assert result.final_outcome == "success"
    assert 0 in result.skipped_steps
    assert 1 in result.completed_steps


def test_step_failure_without_can_fail_aborts():
    plan = TaskPlan(task_summary="t", steps=[
        step(0), step(1, depends_on=[0]),
    ])
    se = ScriptedStepExecutor(failures={0: "fatal tool error"})

    executor = build_executor(se)
    result = executor.execute(plan, task_id="t11", original_task="x")

    assert result.final_outcome == "aborted"
    assert 1 not in result.completed_steps
    assert se.calls == [0]


# -- history is recorded across the whole flow -------------------------------

def test_history_captures_checkpoint_and_replan_decisions():
    plan = TaskPlan(task_summary="t", steps=[
        step(0, can_replan=True), step(1, depends_on=[0]),
    ])
    se = ScriptedStepExecutor()
    checkpoint = MockCheckpointEvaluator(by_step={
        0: CheckpointResult(CheckpointVerdict.INVALID, "moved", "location"),
    })

    class RepairingReplanner(MockReplanner):
        def replan(self, request):
            self.calls.append(request)
            return request.original_plan.with_replaced_tail(1, [step(1, depends_on=[0])])

    replanner = RepairingReplanner()

    with tempfile.TemporaryDirectory() as d:
        history = ExecutionHistoryStore(d)
        executor = build_executor(se, checkpoint_evaluator=checkpoint,
                                   local_replanner=replanner, history_store=history)
        result = executor.execute(plan, task_id="t12", original_task="x")

        attempts = history.get_attempts("t12")
        assert len(attempts) == 1
        a = attempts[0]
        assert a.final_outcome == "success"
        assert a.checkpoint_decisions[0]["verdict"] == "invalid"
        assert a.replans[0]["kind"] == "local"
        assert a.invalidated_assumptions == ["location"]


# -- full replan receives prior-attempt history (task_id threading) ---------

def test_full_replan_receives_previous_attempt_history():
    plan = TaskPlan(task_summary="t", steps=[step(0)])
    se = ScriptedStepExecutor()

    captured_requests = []

    class CapturingReplanner(MockReplanner):
        def replan(self, request):
            captured_requests.append(request)
            self.calls.append(request)
            return TaskPlan(task_summary="t (retry)", steps=[step(0)], parent_plan_id=request.original_plan.plan_id)

    final_validator = MockFinalValidator(results=[
        FinalValidationResult(FinalOutcome.FAIL, "goal not met"),
        FinalValidationResult(FinalOutcome.PASS, "now it is"),
    ])
    full_replanner = CapturingReplanner()

    with tempfile.TemporaryDirectory() as d:
        history = ExecutionHistoryStore(d)
        # Seed a prior, already-finalized attempt for the same task_id.
        prior_plan = TaskPlan(task_summary="t", steps=[step(0)])
        prior_attempt = history.start_attempt("t13", "x", prior_plan)
        history.record_execution_failure(prior_attempt, 0, "old_str not found in forms.py")
        history.finalize_attempt(prior_attempt, outcome="failure", failure_reason="edit kept failing")

        executor = build_executor(se, full_replanner=full_replanner,
                                   final_validator=final_validator, history_store=history)
        result = executor.execute(plan, task_id="t13", original_task="x")

    assert result.final_outcome == "success"
    assert len(captured_requests) == 1
    summary = captured_requests[0].previous_attempts_summary
    assert "old_str not found in forms.py" in summary
    assert "edit kept failing" in summary