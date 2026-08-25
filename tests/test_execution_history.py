import json
import os
import tempfile

import pytest

from src.core.task_plan import TaskPlan, TaskStep, ActionType
from src.core.executor.execution_history import ExecutionHistoryStore


def make_plan():
    return TaskPlan(task_summary="add validation", steps=[
        TaskStep(step_id=0, description="think", action_type=ActionType.THINK),
    ])


@pytest.fixture
def store_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_start_attempt_persists_immediately(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()
    attempt_id = store.start_attempt("task-1", "add validation to schema", plan)

    path = os.path.join(store_dir, "task-1", f"{attempt_id}.json")
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["original_task"] == "add validation to schema"
    assert data["final_outcome"] is None


def test_full_attempt_lifecycle_round_trips(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()
    attempt_id = store.start_attempt("task-1", "add validation", plan)

    store.record_step_completed(attempt_id, 0, "found form class")
    store.record_checkpoint_decision(attempt_id, 0, "invalid", "file moved")
    store.record_replan(attempt_id, kind="local", reason="file moved",
                         invalidated_assumption="forms.py location", new_plan_id="plan-2")
    store.record_execution_failure(attempt_id, 1, "old_str not found")
    store.finalize_attempt(attempt_id, outcome="success")

    attempts = store.get_attempts("task-1")
    assert len(attempts) == 1
    a = attempts[0]
    assert a.final_outcome == "success"
    assert a.completed_steps == [0]
    assert a.checkpoint_decisions[0]["verdict"] == "invalid"
    assert a.replans[0]["kind"] == "local"
    assert a.invalidated_assumptions == ["forms.py location"]
    assert a.execution_failures[0]["error"] == "old_str not found"


def test_finalize_removes_from_active_attempts(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()
    attempt_id = store.start_attempt("task-1", "add validation", plan)
    store.finalize_attempt(attempt_id, outcome="success")

    with pytest.raises(KeyError):
        store.record_step_completed(attempt_id, 0, "x")  # attempt no longer active


def test_relevant_history_text_empty_for_new_task(store_dir):
    store = ExecutionHistoryStore(store_dir)
    assert store.relevant_history_text("never-seen-task") == ""


def test_relevant_history_text_surfaces_failures_for_next_planning_call(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()
    attempt_id = store.start_attempt("task-1", "add validation", plan)
    store.record_execution_failure(attempt_id, 0, "old_str not found in forms.py")
    store.finalize_attempt(attempt_id, outcome="failure", failure_reason="edit failed repeatedly")

    text = store.relevant_history_text("task-1")
    assert "old_str not found in forms.py" in text
    assert "edit failed repeatedly" in text


def test_multiple_attempts_ordered_by_start_time(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()

    a1 = store.start_attempt("task-1", "add validation", plan)
    store.finalize_attempt(a1, outcome="failure", failure_reason="first try failed")

    a2 = store.start_attempt("task-1", "add validation", plan)
    store.finalize_attempt(a2, outcome="success")

    attempts = store.get_attempts("task-1")
    assert [a.attempt_id for a in attempts] == [a1, a2]


def test_history_separate_per_task_id(store_dir):
    store = ExecutionHistoryStore(store_dir)
    plan = make_plan()
    store.start_attempt("task-1", "goal A", plan)
    store.start_attempt("task-2", "goal B", plan)

    assert len(store.get_attempts("task-1")) == 1
    assert len(store.get_attempts("task-2")) == 1