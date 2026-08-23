"""
test_orchestrator.py — NEW MODIFY TESTS

Append these to your existing test_orchestrator.py file.
Existing tests for run() remain unchanged.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.orchestrator.orchestrator import Orchestrator, ModifyResult
from src.context.context_store import ContextStore
from src.orchestrator.triviality_judge import ChangeClassification
from src.orchestrator.grilling import DeltaGrillingResult, DeltaFinalizationError


SAMPLE_CONTEXT = """### Problem Statement
Build a task management app.

### Functional Requirements
1. Users can create tasks.
2. Users can mark tasks complete.

### Assumptions
1. Single-user initially.

### Shared Vocabulary
- Task: an item to do.
"""


def test_modify_raises_if_project_not_found():
    """modify() should raise if CONTEXT.md doesn't exist."""
    store = ContextStore()
    orch = Orchestrator(context_store=store)
    
    with pytest.raises(ValueError, match="No CONTEXT.md found"):
        orch.modify("nonexistent-project", "Add some feature")


def test_modify_trivial_change_skips_delta_interview():
    """Trivial changes skip delta interview, go straight to gateway."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Here's your code.")
    
    # Mock classifier to return trivial
    trivial_classification = ChangeClassification(
        verdict="trivial",
        reason="Renaming a variable.",
        affected_sections=[],
    )
    
    with patch("orchestrator.classify_change", return_value=trivial_classification):
        result = orch.modify("test-project", "Rename taskId to task_id")
    
    assert result.was_trivial
    assert result.sections_updated == []
    assert result.updated_context_md == SAMPLE_CONTEXT  # Unchanged
    assert result.response == "Here's your code."


def test_modify_significant_change_runs_delta_interview():
    """Significant changes trigger delta interview + merge."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Code for recurring tasks.")
    
    # Mock classifier to return significant
    sig_classification = ChangeClassification(
        verdict="significant",
        reason="New functional requirement.",
        affected_sections=["Functional Requirements", "Shared Vocabulary"],
    )
    
    # Mock delta grilling result
    delta_result = DeltaGrillingResult(
        answers={
            "Functional Requirements": "3. Users can create recurring tasks.",
            "Shared Vocabulary": "- Recurrence: repeat schedule.",
        },
        change_summary="Added recurring task support.",
        conversation_history=[],
        ask_count=3,
        successfully_finalized=True,
    )
    
    with patch("orchestrator.classify_change", return_value=sig_classification):
        with patch.object(orch.grilling_runner, "start_delta_interview"):
            with patch.object(orch.grilling_runner, "finalize_delta", return_value=delta_result):
                # Mock stdin to avoid interactive prompt
                with patch("sys.stdin.isatty", return_value=False):
                    result = orch.modify("test-project", "Add recurring tasks")
    
    assert not result.was_trivial
    assert "Functional Requirements" in result.sections_updated
    assert "**Update:** 3. Users can create recurring tasks." in result.updated_context_md
    assert "**Update:** - Recurrence: repeat schedule." in result.updated_context_md
    assert "Change Log" in result.updated_context_md


def test_modify_saves_updated_context():
    """modify() should persist the updated CONTEXT.md to disk."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Response")
    
    sig_classification = ChangeClassification(
        verdict="significant",
        reason="Test.",
        affected_sections=["Functional Requirements"],
    )
    
    delta_result = DeltaGrillingResult(
        answers={"Functional Requirements": "New feature X."},
        change_summary="Added feature X.",
        conversation_history=[],
        ask_count=2,
        successfully_finalized=True,
    )
    
    with patch("orchestrator.classify_change", return_value=sig_classification):
        with patch.object(orch.grilling_runner, "start_delta_interview"):
            with patch.object(orch.grilling_runner, "finalize_delta", return_value=delta_result):
                with patch("sys.stdin.isatty", return_value=False):
                    result = orch.modify("test-project", "Add feature X")
    
    # Reload from disk to verify it was saved
    persisted = store.load("test-project")
    assert "**Update:** New feature X." in persisted
    assert "Change Log" in persisted


def test_modify_flags_sections_not_found():
    """If delta interview mentions a nonexistent section, flag it in warnings."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Response")
    
    sig_classification = ChangeClassification(
        verdict="significant",
        reason="Test.",
        affected_sections=["Nonexistent Section"],
    )
    
    delta_result = DeltaGrillingResult(
        answers={"Nonexistent Section": "Some content"},
        change_summary="Test.",
        conversation_history=[],
        ask_count=2,
        successfully_finalized=True,
    )
    
    with patch("orchestrator.classify_change", return_value=sig_classification):
        with patch.object(orch.grilling_runner, "start_delta_interview"):
            with patch.object(orch.grilling_runner, "finalize_delta", return_value=delta_result):
                with patch("sys.stdin.isatty", return_value=False):
                    result = orch.modify("test-project", "Test change")
    
    assert len(result.merge_warnings) > 0
    assert any("Nonexistent Section" in w for w in result.merge_warnings)


def test_modify_classifier_error_defaults_to_significant():
    """If classifier raises, default to significant (safer)."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Response")
    
    delta_result = DeltaGrillingResult(
        answers={"Functional Requirements": "Test update."},
        change_summary="Test.",
        conversation_history=[],
        ask_count=1,
        successfully_finalized=True,
    )
    
    with patch("orchestrator.classify_change", side_effect=Exception("Classifier boom")):
        with patch.object(orch.grilling_runner, "start_delta_interview"):
            with patch.object(orch.grilling_runner, "finalize_delta", return_value=delta_result):
                with patch("sys.stdin.isatty", return_value=False):
                    # Should not raise; should treat as significant
                    result = orch.modify("test-project", "Test change")
    
    # If it defaulted to significant, the delta interview ran
    assert "Test update" in result.updated_context_md


def test_modify_delta_finalization_error_allows_abort():
    """If delta interview fails to parse, user can abort or continue."""
    store = ContextStore()
    store.save("test-project", SAMPLE_CONTEXT)
    
    orch = Orchestrator(context_store=store)
    orch.gateway.handle = MagicMock(return_value="Response")
    
    sig_classification = ChangeClassification(
        verdict="significant",
        reason="Test.",
        affected_sections=["Functional Requirements"],
    )
    
    with patch("orchestrator.classify_change", return_value=sig_classification):
        with patch.object(orch.grilling_runner, "start_delta_interview"):
            with patch.object(
                orch.grilling_runner,
                "finalize_delta",
                side_effect=DeltaFinalizationError("Malformed JSON"),
            ):
                with patch("sys.stdin.isatty", return_value=False):
                    # Non-interactive mode, finalization error, should raise
                    with pytest.raises(DeltaFinalizationError):
                        orch.modify("test-project", "Test change")