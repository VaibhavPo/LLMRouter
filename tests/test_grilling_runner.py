"""
test_grilling_runner.py — NEW DELTA TESTS

Append these to your existing test_grilling_runner.py file.
Existing tests for start_interview, continue_interview, finalize remain unchanged.
"""

import pytest
from src.orchestrator.grilling import (
    GrillingRunner,
    DeltaGrillingResult,
    DeltaFinalizationError,
)


def _mock_delta_runner(response_text: str):
    """Returns a fake model_runner for delta grilling."""
    def runner(model_id: str, prompt: str) -> str:
        return response_text
    return runner


# ========== START_DELTA_INTERVIEW ==========

def test_start_delta_interview_seeds_with_context_and_change():
    """Verify the delta interview is seeded with existing context and change."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("What's your priority for this?"))
    
    msg = runner.start_delta_interview(
        context_md="### Problem Statement\nA task app.\n\n### Functional Requirements\n1. Tasks must be createable.",
        change_request="Add support for recurring tasks.",
        affected_sections=["Functional Requirements"],
    )
    
    assert msg.ask_count == 1
    assert msg.question == "What's your priority for this?"
    assert not msg.is_finalizing
    assert len(runner._conversation_history) == 2


def test_start_delta_interview_resets_history():
    """Delta interview should not mix with prior full grilling history."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("First Q"))
    
    # Start full grilling, add history
    msg1 = runner.start_interview("Build a blog app")
    runner.continue_interview("I want it to be fast")
    
    # Now start delta interview — history should be reset
    msg2 = runner.start_delta_interview(
        context_md="### Problem Statement\nA blog.",
        change_request="Add comments.",
        affected_sections=[],
    )
    
    # Only the delta interview's exchanges in history
    assert len(runner._conversation_history) == 2
    assert "Build a blog app" not in runner._conversation_history[0].content


# ========== CONTINUE_DELTA_INTERVIEW ==========

def test_continue_delta_interview_respects_max_questions():
    """Delta interview has hard ceiling at MAX_DELTA_QUESTIONS (5)."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("Q: test"))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest",
        change_request="test",
        affected_sections=[],
    )
    
    # Ask 4 more times (1 from start + 4 from continue = 5 total)
    for _ in range(4):
        runner.continue_delta_interview("answer")
    
    # 6th attempt should raise
    with pytest.raises(RuntimeError, match="max delta questions"):
        runner.continue_delta_interview("answer")


def test_continue_delta_interview_builds_conversation():
    """Conversation history grows with each turn."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("Follow-up question"))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest",
        change_request="test",
        affected_sections=[],
    )
    assert len(runner._conversation_history) == 2
    
    runner.continue_delta_interview("First answer")
    assert len(runner._conversation_history) == 4


# ========== FINALIZE_DELTA ==========

def test_finalize_delta_parses_valid_json():
    """finalize_delta should extract answers and change_summary from JSON."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("dummy"))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest\n\n### Functional Requirements\ntest",
        change_request="test",
        affected_sections=["Functional Requirements"],
    )
    
    json_response = (
        '{"answers": {"Functional Requirements": "Tasks can now recur."}, '
        '"change_summary": "Added recurring task support."}'
    )
    runner._conversation_history.clear()  # Clear for cleaner test
    runner._model_runner = _mock_delta_runner(json_response)
    runner.start_delta_interview(
        context_md="### Problem\ntest\n\n### Functional Requirements\ntest",
        change_request="test",
        affected_sections=["Functional Requirements"],
    )
    
    result = runner.finalize_delta(affected_sections=["Functional Requirements"])
    
    assert result.successfully_finalized
    assert result.answers == {"Functional Requirements": "Tasks can now recur."}
    assert result.change_summary == "Added recurring task support."


def test_finalize_delta_raises_on_missing_json():
    """finalize_delta should raise DeltaFinalizationError if no JSON found."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("Just prose, no JSON."))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest",
        change_request="test",
        affected_sections=[],
    )
    
    with pytest.raises(DeltaFinalizationError, match="No JSON object found"):
        runner.finalize_delta(affected_sections=[])


def test_finalize_delta_raises_on_malformed_json():
    """finalize_delta should raise if JSON is malformed."""
    runner = GrillingRunner(model_runner=_mock_delta_runner('{"answers": invalid json'))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest",
        change_request="test",
        affected_sections=[],
    )
    
    with pytest.raises(DeltaFinalizationError, match="Malformed JSON"):
        runner.finalize_delta(affected_sections=[])


def test_finalize_delta_raises_on_missing_required_fields():
    """finalize_delta should raise if 'answers' or 'change_summary' missing."""
    runner = GrillingRunner(model_runner=_mock_delta_runner('{"other_field": "value"}'))
    
    runner.start_delta_interview(
        context_md="### Problem\ntest",
        change_request="test",
        affected_sections=[],
    )
    
    with pytest.raises(DeltaFinalizationError, match="missing"):
        runner.finalize_delta(affected_sections=[])


def test_finalize_delta_multiple_sections():
    """finalize_delta should handle multiple affected sections."""
    runner = GrillingRunner(model_runner=_mock_delta_runner("dummy"))
    
    json_response = (
        '{"answers": {'
        '"Functional Requirements": "Recurring tasks added.", '
        '"Shared Vocabulary": "Recurrence rule: repeat schedule." '
        '}, '
        '"change_summary": "Added recurring + vocab."}'
    )
    runner._model_runner = _mock_delta_runner(json_response)
    
    runner.start_delta_interview(
        context_md="### Problem\ntest\n\n### Functional Requirements\ntest\n\n### Shared Vocabulary\ntest",
        change_request="test",
        affected_sections=["Functional Requirements", "Shared Vocabulary"],
    )
    
    result = runner.finalize_delta(affected_sections=["Functional Requirements", "Shared Vocabulary"])
    
    assert len(result.answers) == 2
    assert "Recurring tasks added" in result.answers["Functional Requirements"]