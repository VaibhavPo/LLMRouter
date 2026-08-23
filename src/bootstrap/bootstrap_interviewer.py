"""
bootstrap_interviewer.py — Phase 4.6, Module 3

BootstrapInterviewer turns [UNKNOWN: ...] markers left by
BootstrapRunner.infer() into a short, targeted interview, and returns
the answers as a dict ready for BootstrapRunner.finalise().

Integration with BootstrapRunner.finalise():
    finalise() expects interview_answers as dict[str, str] where:
    - Keys are the text between [UNKNOWN: and ], without brackets
    - Values are the answer strings
    
    Example:
      draft has: [UNKNOWN: Business priority and SLA]
      answers dict: {"Business priority and SLA": "High priority, 99.95% SLA"}
      finalise() replaces with the answer text
    
    The _normalize() function here ensures key extraction matches what
    finalise() will search for, so the two modules agree on keys
    without either importing the other's regex.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# Non-greedy, DOTALL so a marker can't accidentally span past its own
# closing bracket even if the model wraps text across lines.
_UNKNOWN_PATTERN = re.compile(r"\[UNKNOWN:\s*(.*?)\]", re.DOTALL)


def _normalize(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip ends.

    This MUST match the normalization BootstrapRunner.finalise() does
    when matching keys in interview_answers against the draft markdown.
    """
    return " ".join(text.split())


@dataclass
class InterviewResult:
    """Outcome of a full interview pass.

    answers: dict mapping unknown key → answer, ready to pass directly to
             BootstrapRunner.finalise(draft_context_md, answers)
    
    unresolved: keys the user deferred or left blank after reprompting.
                If non-empty, finalise() will raise ValueError when called
                with `answers` as-is. Caller must handle this (re-interview,
                abort, or fallback).
    """

    answers: Dict[str, str] = field(default_factory=dict)
    unresolved: List[str] = field(default_factory=list)


class BootstrapInterviewer:
    """Interactive, one-question-at-a-time interview over [UNKNOWN] markers.

    Entry point:
        interviewer = BootstrapInterviewer()
        result = interviewer.run(draft_context_md)
        # result.answers == {"Business priority and SLA": "...", ...}
        # Pass to BootstrapRunner.finalise(draft, result.answers)
    
    I/O seam (testable without terminal):
        interviewer = BootstrapInterviewer(
            input_fn=mock_input,
            output_fn=mock_output
        )
    """

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        max_reprompts: int = 1,
    ):
        """
        Args:
            input_fn: callable to read user input (injected for testing)
            output_fn: callable to print messages (injected for testing)
            max_reprompts: how many times to ask "please answer this" before
                          marking as unresolved
        """
        self._input = input_fn
        self._output = output_fn
        self._max_reprompts = max_reprompts

    # -- parsing -------------------------------------------------------

    @staticmethod
    def parse_unknowns(draft_context_md: str) -> List[str]:
        """Extract every distinct [UNKNOWN: ...] key, in document order.

        Duplicate markers (same key appearing twice) are collapsed to
        one question — the model should have already clustered related
        unknowns, so duplicates mean "this fact is needed in multiple
        places," not "ask twice."
        
        Args:
            draft_context_md: markdown from BootstrapRunner.infer()
        
        Returns:
            list of keys (text between [UNKNOWN: and ], normalized)
            in order of first appearance
        """
        keys: List[str] = []
        for raw in _UNKNOWN_PATTERN.findall(draft_context_md):
            key = _normalize(raw)
            if key and key not in keys:
                keys.append(key)
        return keys

    # -- interview loop -------------------------------------------------

    def run(self, draft_context_md: str) -> InterviewResult:
        """Run the full interview and return answers for finalise().
        
        Args:
            draft_context_md: markdown with [UNKNOWN: ...] markers
        
        Returns:
            InterviewResult with answers dict and unresolved list.
            If unresolved is non-empty, finalise() will raise ValueError.
        """
        unknowns = self.parse_unknowns(draft_context_md)

        if not unknowns:
            self._output(
                "No [UNKNOWN] entries found — draft CONTEXT.md is already complete."
            )
            return InterviewResult(answers={}, unresolved=[])

        self._output(
            f"\nI read the codebase and filled in what I could. "
            f"{len(unknowns)} thing(s) I couldn't figure out:\n"
        )

        answers: Dict[str, str] = {}
        unresolved: List[str] = []

        for i, key in enumerate(unknowns, start=1):
            answer = self._ask_one(i, len(unknowns), key)
            if answer is None:
                unresolved.append(key)
            else:
                answers[key] = answer

        if unresolved:
            self._output(
                f"\n⚠️  {len(unresolved)} question(s) left unanswered:"
            )
            for key in unresolved:
                self._output(f"    - {key}")

        return InterviewResult(answers=answers, unresolved=unresolved)

    def _ask_one(self, index: int, total: int, key: str) -> Optional[str]:
        """Ask a single question, re-prompting on empty input up to
        max_reprompts times.
        
        Args:
            index: question number (for display)
            total: total questions (for display)
            key: the [UNKNOWN] key to ask about
        
        Returns:
            The user's answer (stripped), or None if still empty after
            max_reprompts or if user types "defer".
        """
        prompt = f"Q{index}/{total}: {key}\n> "
        response = self._input(prompt).strip()

        attempts = 0
        while not response and attempts < self._max_reprompts:
            attempts += 1
            self._output(
                "  (this can't be left blank — finalise() will reject "
                "an unresolved [UNKNOWN]. Type your answer, or 'defer' to skip.)"
            )
            response = self._input(prompt).strip()

        if not response:
            return None
        if response.lower() == "defer":
            return None
        return response
