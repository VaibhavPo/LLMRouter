"""
skills.skill_factory

Public interface: run_skill(skill_name, task, context_md, model_id, model_runner) -> SkillResult

Loads a procedure .md file, injects CONTEXT.md + task, runs the model,
evaluates phase gating / quality checks specific to that skill.
"""

from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from src.core.schema import SkillType

_SKILL_DIR = Path(__file__).parent / "procedures"


@dataclass
class SkillResult:
    skill_name: str
    raw_response: str
    passed: bool  # Did the response pass skill-specific checks?
    feedback: list[str]  # ["phase missing", "invalid structure", ...]
    metadata: dict = None  # Skill-specific (e.g., {"phases_found": ["RED", "GREEN"]})


def _load_procedure(skill_name: str) -> str:
    """Load the .md file for the skill."""
    path = _SKILL_DIR / f"{skill_name.replace('_', '-')}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill procedure not found: {path}")
    return path.read_text(encoding="utf-8")


def run_skill(
    skill_name: SkillType,
    task_description: str,
    context_md: Optional[str] = None,
    model_id: str = "nvidia/nemotron-3-nano-4b",
    model_runner: Optional[Callable[[str, str], str]] = None,
) -> SkillResult:
    """
    Run a skill procedure.

    1. Load the procedure (.md)
    2. Build prompt: procedure + [CONTEXT.md if provided] + task
    3. Run model
    4. Evaluate response against skill-specific checks
    5. Return SkillResult
    """
    if model_runner is None:
        from src.core.gateway import _lmstudio_run
        runner = _lmstudio_run
    else:
        runner = model_runner

    procedure = _load_procedure(skill_name.value)

    # Build prompt: procedure → CONTEXT.md → task
    prompt_parts = [procedure]
    if context_md:
        prompt_parts.append(f"\n\n--- CONTEXT ---\n{context_md}\n--- END CONTEXT ---")
    prompt_parts.append(f"\n\n{task_description}")
    prompt = "".join(prompt_parts)

    response = runner(model_id, prompt)

    # Skill-specific evaluation (delegated)
    result = _evaluate_skill_response(skill_name, response)
    result.raw_response = response

    return result


def _evaluate_skill_response(skill_name: SkillType, response: str) -> SkillResult:
    """Dispatch to skill-specific evaluator."""
    evaluators = {
        SkillType.TDD: _evaluate_tdd,
        SkillType.DIAGNOSIS: _evaluate_diagnosis,
        SkillType.PLANNING: _evaluate_planning,
        SkillType.CODE_REVIEW: _evaluate_code_review,
        SkillType.DOMAIN_MODELING: _evaluate_domain_modeling,
        SkillType.UNKNOWN: lambda r: SkillResult(
            skill_name="unknown",
            raw_response=r,
            passed=True,
            feedback=["No skill checks for UNKNOWN"],
        ),
    }
    evaluator = evaluators.get(skill_name, evaluators[SkillType.UNKNOWN])
    return evaluator(response)


def _extract_code_blocks_by_phase(response: str) -> dict[str, str]:
    """Extract the python code block immediately following each ## PHASE header."""
    import re

    _PHASE_HEADER_PATTERN = r"##\s*(RED|GREEN|REFACTOR)\b"
    blocks = {}
    headers = list(re.finditer(_PHASE_HEADER_PATTERN, response, re.IGNORECASE))
    for i, match in enumerate(headers):
        phase = match.group(1).upper()
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(response)
        section = response[start:end]
        code_match = re.search(r"```(?:python)?\s*\n(.*?)```", section, re.DOTALL)
        if code_match:
            blocks[phase] = code_match.group(1)
    return blocks


def _extract_function_defs(code: str) -> dict[str, int]:
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    return {
        node.name: len(node.args.args)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _extract_call_arities(code: str, func_names: set[str]) -> list[tuple[str, int]]:
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in func_names:
                calls.append((node.func.id, len(node.args) + len(node.keywords)))
    return calls


def _evaluate_tdd(response: str) -> SkillResult:
    """
    Check RED/GREEN/REFACTOR phase gating (structural + stub/trivial
    heuristics, delegated to skill_runner.py — the shared source of
    truth for this logic), plus a RED↔GREEN signature consistency check.
    """
    from src.skills.skill_loader  import _evaluate_phase_gating as _tdd_phase_gating_check

    tdd_result = _tdd_phase_gating_check(response)

    _PHASE_ORDER = ["RED", "GREEN", "REFACTOR"]
    feedback = []
    if not tdd_result.all_phases_present:
        feedback.append(f"Missing phases. Found: {tdd_result.phases_found}, Expected: {_PHASE_ORDER}")
    if tdd_result.all_phases_present and not tdd_result.followed_order:
        feedback.append(f"Phases out of order: {tdd_result.phases_found}")
    if tdd_result.red_phase_looks_like_stub:
        feedback.append("RED phase looks like a stub implementation, not a failing test (no assert found)")
    if tdd_result.green_phase_looks_trivial:
        feedback.append("GREEN phase looks trivial — function returns a bare literal, ignoring its own parameters")

    passed = tdd_result.passed  # already combines all four checks above

    # Signature consistency check (RED's calls vs GREEN's definitions)
    if passed:
        code_blocks = _extract_code_blocks_by_phase(response)
        red_code = code_blocks.get("RED", "")
        green_code = code_blocks.get("GREEN", "")
        green_funcs = _extract_function_defs(green_code)
        if green_funcs:
            red_calls = _extract_call_arities(red_code, set(green_funcs.keys()))
            for func_name, call_arity in red_calls:
                expected_arity = green_funcs[func_name]
                if call_arity != expected_arity:
                    passed = False
                    feedback.append(
                        f"Signature mismatch: RED calls {func_name}() with "
                        f"{call_arity} arg(s), GREEN defines it with "
                        f"{expected_arity} param(s)"
                    )

    return SkillResult(
        skill_name="tdd",
        raw_response=response,
        passed=passed,
        feedback=feedback,
        metadata={"phases_found": tdd_result.phases_found},
    )


def _evaluate_diagnosis(response: str) -> SkillResult:
    """Check for MINIMIZE/HYPOTHESIZE/INSTRUMENT/FIX/VERIFY."""
    import re

    _PHASE_ORDER = ["MINIMIZE", "HYPOTHESIZE", "INSTRUMENT", "FIX", "VERIFY"]
    _PHASE_HEADER_PATTERN = r"##\s*(" + "|".join(_PHASE_ORDER) + r")\b"

    matches = [m.upper() for m in re.findall(_PHASE_HEADER_PATTERN, response, re.IGNORECASE)]
    all_present = set(_PHASE_ORDER).issubset(set(matches))

    followed_order = False
    if all_present:
        first_indices = [matches.index(p) for p in _PHASE_ORDER]
        followed_order = first_indices == sorted(first_indices)

    feedback = []
    if not all_present:
        feedback.append(f"Missing phases. Found: {matches}, Expected: {_PHASE_ORDER}")
    if all_present and not followed_order:
        feedback.append(f"Phases out of order: {matches}")

    passed = all_present and followed_order

    return SkillResult(
        skill_name="diagnosis",
        raw_response=response,
        passed=passed,
        feedback=feedback,
        metadata={"phases_found": matches},
    )


def _evaluate_planning(response: str) -> SkillResult:
    """For now: just check that response is non-empty."""
    feedback = []
    if not response or len(response.strip()) < 50:
        feedback.append("Response too short for planning output")

    return SkillResult(
        skill_name="planning",
        raw_response=response,
        passed=len(response.strip()) >= 50,
        feedback=feedback,
    )


def _evaluate_code_review(response: str) -> SkillResult:
    """For now: just check that response is non-empty."""
    feedback = []
    if not response or len(response.strip()) < 50:
        feedback.append("Response too short for code review")

    return SkillResult(
        skill_name="code_review",
        raw_response=response,
        passed=len(response.strip()) >= 50,
        feedback=feedback,
    )


def _evaluate_domain_modeling(response: str) -> SkillResult:
    """For now: just check that response is non-empty."""
    feedback = []
    if not response or len(response.strip()) < 50:
        feedback.append("Response too short for domain modeling")

    return SkillResult(
        skill_name="domain_modeling",
        raw_response=response,
        passed=len(response.strip()) >= 50,
        feedback=feedback,
    )