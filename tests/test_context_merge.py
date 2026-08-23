"""
test_context_merge.py

Offline tests for context_merge.py. No model calls involved — pure string
transformation logic.
"""

from src.orchestrator.modify import merge_context, _split_sections

SAMPLE_CONTEXT = """### Problem Statement
To build a centralized application that allows users to create, track, assign, and manage personal or team tasks efficiently.

### Functional Requirements
1. Users must be able to register, log in, and securely manage their profiles.
2. Users must be able to create new tasks with titles, descriptions, deadlines, and priority levels.

### Assumptions
1. The application will be developed using a standard modern stack.

### Shared Vocabulary
*   **User:** An individual accessing the application.
*   **Task:** A discrete item requiring action.
"""


def test_split_sections_parses_all_headers():
    sections = _split_sections(SAMPLE_CONTEXT)
    assert set(sections.keys()) == {
        "Problem Statement", "Functional Requirements", "Assumptions", "Shared Vocabulary"
    }


def test_merge_only_touches_specified_sections():
    result = merge_context(
        old_context_md=SAMPLE_CONTEXT,
        answers={"Functional Requirements": "Tasks can now recur on a schedule."},
        change_request="Add support for recurring tasks.",
        change_summary="Added recurring task support.",
    )
    assert "Added recurring task support" in result.change_log_entry
    assert result.sections_updated == ["Functional Requirements"]
    # Untouched sections preserved verbatim
    assert "standard modern stack" in result.merged_context
    assert "**User:**" in result.merged_context
    # Touched section has both old and new content
    assert "register, log in" in result.merged_context
    assert "Tasks can now recur on a schedule." in result.merged_context


def test_merge_appends_to_existing_change_log():
    first = merge_context(
        old_context_md=SAMPLE_CONTEXT,
        answers={"Assumptions": "Now assumes recurring-task scheduling library available."},
        change_request="Add recurring tasks.",
        change_summary="Added recurring task support.",
    )
    second = merge_context(
        old_context_md=first.merged_context,
        answers={"Shared Vocabulary": "**Recurrence Rule:** defines how often a task repeats."},
        change_request="Define recurrence rule vocabulary.",
        change_summary="Clarified recurrence terminology.",
    )
    # Both change log entries present, in order
    assert "Added recurring task support" in second.merged_context
    assert "Clarified recurrence terminology" in second.merged_context


def test_merge_flags_unknown_section_without_dropping_it():
    result = merge_context(
        old_context_md=SAMPLE_CONTEXT,
        answers={"Nonexistent Section": "some content"},
        change_request="Some change.",
        change_summary="Some summary.",
    )
    assert result.sections_not_found == ["Nonexistent Section"]
    assert result.sections_updated == []


def test_merge_with_multiple_sections_updates_all():
    result = merge_context(
        old_context_md=SAMPLE_CONTEXT,
        answers={
            "Functional Requirements": "Recurring tasks supported.",
            "Shared Vocabulary": "**Recurrence Rule:** repeat schedule.",
        },
        change_request="Add recurring tasks with defined vocabulary.",
        change_summary="Added recurring tasks + vocab.",
    )
    assert set(result.sections_updated) == {"Functional Requirements", "Shared Vocabulary"}