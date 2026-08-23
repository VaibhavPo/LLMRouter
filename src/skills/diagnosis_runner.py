"""
skills.diagnosis_runner

Public interface:
    run_diagnosis_skill(bug_description, model_id, model_runner) -> DiagnosisResult

Loads diagnosing-bugs.md, injects it into a prompt for a specific model,
and evaluates whether the response held the five-phase gating:
MINIMIZE → HYPOTHESIZE → INSTRUMENT → FIX → VERIFY.

This is a benchmark harness — bypasses classifier/router deliberately,
since the model under test is chosen explicitly.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.core.gateway import _lmstudio_run

_SKILL_DIR = Path(__file__).parent / "procedures"
_DIAGNOSIS_SKILL_PATH = _SKILL_DIR / "diagnosing-bugs.md"

_PHASE_ORDER = ["MINIMIZE", "HYPOTHESIZE", "INSTRUMENT", "FIX", "VERIFY"]
_PHASE_HEADER_PATTERN = r"##\s*(MINIMIZE|HYPOTHESIZE|INSTRUMENT|FIX|VERIFY)\b"


@dataclass
class DiagnosisResult:
    raw_response: str
    phases_found: list = field(default_factory=list)
    all_phases_present: bool = False
    followed_order: bool = False
    hypothesize_is_vague: bool = False
    verify_is_trivial: bool = False

    @property
    def passed(self) -> bool:
        return (
            self.all_phases_present
            and self.followed_order
            and not self.hypothesize_is_vague
            and not self.verify_is_trivial
        )


def _load_skill_text() -> str:
    return _DIAGNOSIS_SKILL_PATH.read_text(encoding="utf-8")


def _extract_section(response: str, start_phase: str, end_phase: str) -> str:
    """Extract text between two phase headers."""
    pattern = rf"##\s*{start_phase}\b(.*?)##\s*{end_phase}\b"
    match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_last_section(response: str, phase: str) -> str:
    """Extract text from a phase header to end of response."""
    pattern = rf"##\s*{phase}\b(.*?)$"
    match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _hypothesize_is_vague(response: str) -> bool:
    """..."""
    section = _extract_section(response, "HYPOTHESIZE", "INSTRUMENT")
    if not section:
        return True
    causal_signals = [
        "because", "due to", "caused by", "when", "if ", "returns",
        "raises", "fails", "overflow", "index", "none", "null",
        "off-by-one", "missing", "incorrect", "wrong",
        "in-place", "mutate", "reference", "modify", "alias",
        "shallow", "deep", "copy", "pointer", "address"
    ]
    vague_patterns = [
        r"something\s+(?:might|may|could)\s+be\s+wrong",
        r"(?:might|may|could)\s+be\s+(?:an?\s+)?issue",
        r"not\s+sure",
        r"possibly\s+",
    ]
    
    lowered = section.lower()
    if any(re.search(pattern, lowered) for pattern in vague_patterns):
        return True
    return not any(signal in lowered for signal in causal_signals)


def _verify_is_trivial(response: str) -> bool:
    """
    Flags VERIFY as trivial if it contains no assert statement or
    specific test function — 'run the tests again' or a vague description
    is not a regression test.
    """
    section = _extract_last_section(response, "VERIFY")
    if not section:
        return True
    has_assert = "assert" in section.lower()
    has_test_func = bool(re.search(r"\bdef\s+test_\w+", section))
    return not (has_assert or has_test_func)


def _evaluate_diagnosis_gating(response: str) -> DiagnosisResult:
    matches = [
        m.upper()
        for m in re.findall(_PHASE_HEADER_PATTERN, response, re.IGNORECASE)
    ]
    all_present = set(_PHASE_ORDER).issubset(set(matches))

    followed_order = False
    if all_present:
        first_indices = [matches.index(p) for p in _PHASE_ORDER]
        followed_order = first_indices == sorted(first_indices)

    return DiagnosisResult(
        raw_response=response,
        phases_found=matches,
        all_phases_present=all_present,
        followed_order=followed_order,
        hypothesize_is_vague=_hypothesize_is_vague(response),
        verify_is_trivial=_verify_is_trivial(response),
    )


def run_diagnosis_skill(
    bug_description: str,
    model_id: str = "essentialai/rnj-1",
    model_runner: Optional[Callable[[str, str], str]] = None,
) -> DiagnosisResult:
    runner = model_runner or _lmstudio_run
    prompt = f"{_load_skill_text()}\n\nBug description: {bug_description}"
    response = runner(model_id, prompt)
    return _evaluate_diagnosis_gating(response)