"""
skills.skill_runner

Public interface: run_tdd_skill(task_description, model_id, model_runner) -> TDDResult

Loads the tdd.md procedure, injects it into a prompt for a specific model,
and evaluates whether the response held RED/GREEN/REFACTOR phase gating —
both structurally (headers present, in order) and semantically at a cheap
level (RED phase isn't just a stub implementation dressed up as a test).
This is a benchmark harness, not a production feature — it deliberately
bypasses the classifier/router, since the model under test is explicit.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.core.gateway import _lmstudio_run

_SKILL_DIR = Path(__file__).parent / "procedures"
_TDD_SKILL_PATH = _SKILL_DIR / "tdd.md"

_PHASE_ORDER = ["RED", "GREEN", "REFACTOR"]
_PHASE_HEADER_PATTERN = r"##\s*(RED|GREEN|REFACTOR)\b"


@dataclass
class TDDResult:
    raw_response: str
    phases_found: list = field(default_factory=list)
    all_phases_present: bool = False
    followed_order: bool = False
    red_phase_looks_like_stub: bool = False
    green_phase_looks_trivial: bool = False    

    @property
    def passed(self) -> bool:
        return (
            self.all_phases_present
            and self.followed_order
            and not self.red_phase_looks_like_stub
            and not self.green_phase_looks_trivial
        )


def _load_skill_text() -> str:
    return _TDD_SKILL_PATH.read_text(encoding="utf-8")


def _red_phase_contains_stub_implementation(response: str) -> bool:
    """
    Cheap heuristic, not a full parser: if the RED section contains a
    function definition but no `assert`, it's very likely a stub
    implementation masquerading as a test — the exact failure mode
    observed in real transcripts before the tdd.md prompt was tightened.
    """
    red_match = re.search(
        r"##\s*RED\b(.*?)##\s*GREEN\b", response, re.IGNORECASE | re.DOTALL
    )
    if not red_match:
        return False
    red_section = red_match.group(1)
    has_def = re.search(r"\bdef\s+\w+\s*\(", red_section)
    has_assert = "assert" in red_section
    return bool(has_def) and not has_assert

def _green_phase_looks_trivial(response: str) -> bool:
    """
    Flags GREEN phase as trivial if the implementation function contains
    only a single return of a bare literal — True/False/None/hardcoded
    string/integer/empty collection — with no real logic above it.
    Docstrings and comments are stripped before counting; a docstring
    doesn't count as "real logic," it's just documentation (or, as seen
    in practice, sometimes the model's own confession that it's a stub).
    """
    green_match = re.search(
        r"##\s*GREEN\b(.*?)##\s*REFACTOR\b", response, re.IGNORECASE | re.DOTALL
    )
    if not green_match:
        return False
    green_section = green_match.group(1)

    func_bodies = re.findall(
        r"def\s+\w+\s*\([^)]*\)\s*:\s*\n((?:[ \t]+.+\n?)*)",
        green_section
    )
    if not func_bodies:
        return False

    for body in func_bodies:
        # Strip triple-quoted docstrings (single- or double-quoted, single or triple)
        stripped = re.sub(r'"""(?:.|\n)*?"""', '', body)
        stripped = re.sub(r"'''(?:.|\n)*?'''", '', stripped)

        real_lines = [
            line.strip() for line in stripped.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        if len(real_lines) == 1 and re.match(
            r"^return\s+(True|False|None|\[\]|\{\}|['\"].*?['\"]|\d+)\s*$",
            real_lines[0]
        ):
            return True

    return False


def _evaluate_phase_gating(response: str) -> TDDResult:
    matches = [m.upper() for m in re.findall(_PHASE_HEADER_PATTERN, response, re.IGNORECASE)]
    all_present = set(_PHASE_ORDER).issubset(set(matches))

    followed_order = False
    if all_present:
        first_indices = [matches.index(p) for p in _PHASE_ORDER]
        followed_order = first_indices == sorted(first_indices)

    return TDDResult(
        raw_response=response,
        phases_found=matches,
        all_phases_present=all_present,
        followed_order=followed_order,
        red_phase_looks_like_stub=_red_phase_contains_stub_implementation(response),
        green_phase_looks_trivial=_green_phase_looks_trivial(response),   
    )


def run_tdd_skill(
    task_description: str,
    model_id: str = "nvidia/nemotron-3-nano-4b",
    model_runner: Optional[Callable[[str, str], str]] = None,
) -> TDDResult:
    runner = model_runner or _lmstudio_run
    prompt = f"{_load_skill_text()}\n\nTask: {task_description}"
    response = runner(model_id, prompt)
    return _evaluate_phase_gating(response)