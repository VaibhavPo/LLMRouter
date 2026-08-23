# run_change_classifier_benchmark.py

from change_classifier import classify_change

# A realistic CONTEXT.md for a task management app
# (same domain as the grilling demo you already ran)
SAMPLE_CONTEXT = """
## Problem Statement
A web app for individuals to track personal tasks with deadlines and priority levels.
Target users: solo professionals, students.

## Functional Requirements
- Users can create, edit, and delete tasks
- Each task has: title, description, due date, priority (low/medium/high), status (open/done)
- Users can filter tasks by priority and status
- Tasks are stored per user account (email + password auth)

## Non-Functional Requirements
- Page load under 2 seconds
- Works on mobile browsers

## Tech Stack
- Frontend: React
- Backend: FastAPI
- Database: PostgreSQL

## Architecture
- REST API backend, single-page frontend
- JWT-based auth

## Shared Vocabulary
- Task: the core unit of work (title + metadata)
- Priority: urgency level (low/medium/high), set by user
- Status: completion state (open/done)

## Assumptions
- Single user per account (no team sharing)
- No recurring tasks
- No file attachments

## Open Questions
- Should completed tasks be archived or permanently deleted?
"""

# Each case: (change_request, expected_verdict, explanation_for_reviewer)
BENCHMARK_CASES = [
    (
        "Fix a typo in the error message returned when login fails",
        "trivial",
        "No requirement touched — pure copy change"
    ),
    (
        "Add a 'due today' filter to the task list",
        "significant",
        "New filter type not in Functional Requirements"
    ),
    (
        "Rename the internal variable `task_obj` to `task_record` in the service layer",
        "trivial",
        "Internal refactor, no spec impact"
    ),
    (
        "Add support for recurring tasks",
        "significant",
        "Directly contradicts an Assumption ('No recurring tasks')"
    ),
    (
        "Add a log statement when a task is deleted",
        "trivial",
        "Logging only, no requirement change"
    ),
    (
        "Allow users to attach files to tasks",
        "significant",
        "Directly contradicts an Assumption ('No file attachments')"
    ),
    (
        "Change the JWT token expiry from 1 hour to 24 hours",
        "significant",
        "Modifies auth behaviour — security assumption change"
    ),
    (
        "Fix the button alignment on the task creation form",
        "trivial",
        "UI polish, no spec reference"
    ),
]


def run():
    passed = 0
    failed = 0

    for i, (change_request, expected, note) in enumerate(BENCHMARK_CASES, 1):
        print(f"\n--- Case {i} ---")
        print(f"Change: {change_request}")
        print(f"Expected: {expected}")

        result = classify_change(SAMPLE_CONTEXT, change_request)

        status = "✅ PASS" if result.verdict == expected else "❌ FAIL"
        if result.verdict == expected:
            passed += 1
        else:
            failed += 1

        print(f"Got:      {result.verdict}  {status}")
        print(f"Reason:   {result.reason}")
        if result.affected_sections:
            print(f"Sections: {result.affected_sections}")

    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(BENCHMARK_CASES)} passed")
    if failed == 0:
        print("✅ Classifier ready to wire in")
    else:
        print("❌ Do NOT wire in — fix prompt or switch model first")


if __name__ == "__main__":
    run()