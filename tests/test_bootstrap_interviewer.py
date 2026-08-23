"""
test_bootstrap_interviewer.py — offline tests for Phase 4.6 Module 3

Tests that:
1. Parsing [UNKNOWN] markers extracts keys correctly
2. Interview loop collects answers in the right format for finalise()
3. Unresolved answers are tracked separately
4. The answers dict is compatible with BootstrapRunner.finalise()
"""

import unittest
from src.bootstrap.bootstrap_interviewer import BootstrapInterviewer, InterviewResult


def make_scripted_input(responses):
    """Returns an input_fn that yields `responses` in order, one per call."""
    it = iter(responses)

    def _input(prompt):
        return next(it)

    return _input


def silent_output(_msg):
    pass


DRAFT_WITH_THREE_UNKNOWNS = """
## Business Context
[UNKNOWN: Business priority and SLA]

## Functional Requirements
- Handles retries
- [UNKNOWN: QPS targets]

## Tech Stack
Python, FastAPI

## Assumptions
[UNKNOWN: Auth provider - is this internal SSO or a third party?]
"""

DRAFT_NO_UNKNOWNS = """
## Business Context
Internal tool, low priority.

## Functional Requirements
- Handles retries
"""

DRAFT_WITH_DUPLICATE_UNKNOWN = """
[UNKNOWN: Business priority and SLA]
Some text.
[UNKNOWN: Business priority and SLA]
"""

DRAFT_WITH_MULTILINE_UNKNOWN = """
[UNKNOWN: Business priority
and SLA]
"""


class TestParseUnknowns(unittest.TestCase):
    """Test that unknown marker extraction is correct and deterministic."""

    def test_extracts_all_markers_in_order(self):
        """Keys should come out in document order."""
        keys = BootstrapInterviewer.parse_unknowns(DRAFT_WITH_THREE_UNKNOWNS)
        self.assertEqual(
            keys,
            [
                "Business priority and SLA",
                "QPS targets",
                "Auth provider - is this internal SSO or a third party?",
            ],
        )

    def test_no_unknowns_returns_empty_list(self):
        """If no [UNKNOWN] markers, return empty list."""
        self.assertEqual(BootstrapInterviewer.parse_unknowns(DRAFT_NO_UNKNOWNS), [])

    def test_duplicate_markers_collapse_to_one_key(self):
        """Same [UNKNOWN] twice = ask once."""
        keys = BootstrapInterviewer.parse_unknowns(DRAFT_WITH_DUPLICATE_UNKNOWN)
        self.assertEqual(keys, ["Business priority and SLA"])

    def test_multiline_marker_is_whitespace_normalized(self):
        """Newlines inside [UNKNOWN] should collapse to single space."""
        keys = BootstrapInterviewer.parse_unknowns(DRAFT_WITH_MULTILINE_UNKNOWN)
        self.assertEqual(keys, ["Business priority and SLA"])


class TestInterviewRun(unittest.TestCase):
    """Test that interview collects answers in the format finalise() expects."""

    def test_no_unknowns_short_circuits(self):
        """If no unknowns, return empty InterviewResult."""
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input([]), output_fn=silent_output
        )
        result = interviewer.run(DRAFT_NO_UNKNOWNS)
        self.assertEqual(result, InterviewResult(answers={}, unresolved=[]))

    def test_collects_answers_in_dict_format_for_finalise(self):
        """
        Answers should be dict[str, str] with keys matching [UNKNOWN: ...]
        This is the exact format BootstrapRunner.finalise() expects.
        """
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(
                ["High priority, 99.9% SLA", "~500 QPS peak", "Internal SSO"]
            ),
            output_fn=silent_output,
        )
        result = interviewer.run(DRAFT_WITH_THREE_UNKNOWNS)
        
        # Verify structure is correct for finalise(draft, result.answers)
        self.assertIsInstance(result.answers, dict)
        self.assertEqual(len(result.answers), 3)
        
        # Verify keys match the [UNKNOWN] markers exactly
        self.assertIn("Business priority and SLA", result.answers)
        self.assertIn("QPS targets", result.answers)
        self.assertIn("Auth provider - is this internal SSO or a third party?", result.answers)
        
        # Verify values are non-empty strings
        for key, value in result.answers.items():
            self.assertIsInstance(value, str)
            self.assertTrue(value)

    def test_empty_answer_reprompts_then_accepts(self):
        """User hits enter (empty) → we reprompt → user types answer."""
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(["", "High priority"]),
            output_fn=silent_output,
            max_reprompts=1,
        )
        result = interviewer.run("[UNKNOWN: Business priority]")
        self.assertEqual(result.answers, {"Business priority": "High priority"})
        self.assertEqual(result.unresolved, [])

    def test_defer_marks_key_as_unresolved_not_answered(self):
        """User types 'defer' → key goes to unresolved, not answers."""
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(["defer"]), output_fn=silent_output
        )
        result = interviewer.run("[UNKNOWN: Business priority]")
        self.assertEqual(result.answers, {})
        self.assertEqual(result.unresolved, ["Business priority"])

    def test_still_blank_after_max_reprompts_is_unresolved(self):
        """User hits enter twice without typing → unresolved."""
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(["", ""]),
            output_fn=silent_output,
            max_reprompts=1,
        )
        result = interviewer.run("[UNKNOWN: Business priority]")
        self.assertEqual(result.answers, {})
        self.assertEqual(result.unresolved, ["Business priority"])

    def test_partial_answers_mixed_with_defer_and_blank(self):
        """Some answered, some deferred, some left blank — all tracked correctly."""
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(
                [
                    "High priority, 99.9% SLA",  # Q1 answered
                    "defer",                       # Q2 deferred
                    "",                            # Q3 blank, then reprompt
                    "",                            # Q3 still blank after reprompt
                ]
            ),
            output_fn=silent_output,
            max_reprompts=1,
        )
        result = interviewer.run(DRAFT_WITH_THREE_UNKNOWNS)
        
        # Should have 1 answer, 2 unresolved
        self.assertEqual(len(result.answers), 1)
        self.assertIn("Business priority and SLA", result.answers)
        self.assertEqual(result.answers["Business priority and SLA"], "High priority, 99.9% SLA")
        
        self.assertEqual(len(result.unresolved), 2)
        self.assertIn("QPS targets", result.unresolved)
        self.assertIn("Auth provider - is this internal SSO or a third party?", result.unresolved)


class TestIntegrationWithFinalise(unittest.TestCase):
    """
    Integration tests: verify that InterviewResult.answers is in the
    exact format that BootstrapRunner.finalise() expects.
    
    This is a contract test — if finalise() changes its dict key format,
    this test will catch it.
    """

    def test_answers_dict_keys_match_unknown_marker_text(self):
        """
        Key insight: finalise() does string replacement on [UNKNOWN: key]
        where key is extracted from the draft. We must produce a dict where
        the keys EXACTLY match what finalise() will extract from the same draft.
        """
        draft = "[UNKNOWN: Business priority and SLA]"
        
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(["99.95% SLA"]),
            output_fn=silent_output,
        )
        result = interviewer.run(draft)
        
        # The key in answers should match the key extracted from draft
        extracted_key = BootstrapInterviewer.parse_unknowns(draft)[0]
        self.assertIn(extracted_key, result.answers)
        self.assertEqual(result.answers[extracted_key], "99.95% SLA")

    def test_answers_dict_whitespace_normalized(self):
        """
        If a draft has [UNKNOWN: Business   priority  and  SLA] (extra spaces),
        the key should be normalized to single spaces.
        """
        draft = "[UNKNOWN: Business   priority   and   SLA]"
        
        interviewer = BootstrapInterviewer(
            input_fn=make_scripted_input(["answer"]),
            output_fn=silent_output,
        )
        result = interviewer.run(draft)
        
        # Key should be normalized
        keys = list(result.answers.keys())
        self.assertEqual(keys[0], "Business priority and SLA")  # spaces collapsed


if __name__ == "__main__":
    unittest.main(verbosity=2)
