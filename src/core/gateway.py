"""
llm_gateway.gateway

Public interface: LLMGateway.handle(raw_request) -> str

Everything else in this file is a private implementation detail —
model registry, routing rule, classifier prompt, reasoning-leak strip,
vision override. Callers should never need to know these exist.
"""

from src.core.schema import SkillType
import json
import re
from enum import Enum
from typing import Callable, Optional
from src.skills.skill_factory import run_skill, SkillResult
from pydantic import BaseModel
import lmstudio as lms


# --- Public vocabulary — small enough to export safely -----------------

class TaskType(str, Enum):
    SIMPLE_CODE = "simple_code"
    LARGE_CONTEXT_CODE = "large_context_code"
    REASONING = "reasoning"
    VISION = "vision"


class RoutingError(Exception):
    pass


class InferenceError(Exception):
    pass


# --- Private: model registry --------------------------------------------

class _ModelRole(str, Enum):
    FAST_CODER = "fast_coder"
    CONTEXT_CODER = "context_coder"
    REASONER = "reasoner"        # ← ADD THIS
    VISION = "vision"

_MODEL_REGISTRY: dict[_ModelRole, Optional[str]] = {
    _ModelRole.FAST_CODER: "nvidia/nemotron-3-nano-4b",
    _ModelRole.CONTEXT_CODER: "essentialai/rnj-1",
    _ModelRole.REASONER: None,   # ← ADD THIS — not yet benchmarked, so routing to REASONING will raise RoutingError until you assign one, which is correct fail-loud behavior rather than crashing on a missing enum member
    _ModelRole.VISION: None,
}

_CLASSIFIER_MODEL_ID = "qwen/qwen3-1.7b"
_CONTEXT_ESCALATION_THRESHOLD = 3000
_REASONING_END_MARKER = r"__LM_STUDIO_INTERNAL_LSEP_SYNTHETIC_REASONING_END_[a-f0-9]+__"
_VISION_SIGNALS = (".png", ".jpg", ".jpeg", ".webp", "screenshot", "image")

_CLASSIFIER_SYSTEM_PROMPT = """You are a task classifier. Given a user's coding request,
respond with ONLY a JSON object, no other text, in this exact shape:
{"task_type": "simple_code" | "large_context_code" | "reasoning" | "vision",
 "skill_name": "tdd" | "diagnosis" | "planning" | "code_review" | "domain_modeling" | "unknown",
 "complexity": "low" | "medium" | "high",
 "requires_vision": true | false,
 "requires_reasoning": true | false}
"""


class _Classification(BaseModel):
    task_type: TaskType
    skill_name: SkillType = SkillType.UNKNOWN
    complexity: str
    requires_vision: bool
    requires_reasoning: bool


# --- Private: pure deterministic logic (no I/O, cheap to test) ---------

def _route(task_type: TaskType, context_tokens: int = 0) -> str:
    if task_type == TaskType.VISION:
        raise RoutingError(
            "Vision routing disabled: qwen3-vl-4b not yet benchmarked."
        )
    if task_type == TaskType.REASONING:
        role = _ModelRole.REASONER
    elif task_type == TaskType.LARGE_CONTEXT_CODE or context_tokens > _CONTEXT_ESCALATION_THRESHOLD:
        role = _ModelRole.CONTEXT_CODER
    elif task_type == TaskType.SIMPLE_CODE:
        role = _ModelRole.FAST_CODER
    else:
        raise RoutingError(f"Unrecognized task_type: {task_type!r}")

    model_id = _MODEL_REGISTRY[role]
    if model_id is None:
        raise RoutingError(f"No benchmarked model assigned to role {role}")
    return model_id


# Confirmed: LM Studio has Enable Thinking correctly ON for
# nemotron-3-nano-4b, but the reasoning/content split still fails
# internally for this architecture. This strip is the permanent fix,
# not a stopgap; it also covers other reasoning-tagged models if they
# exhibit the same architecture-level parsing gap.

def _strip_leaked_reasoning(text: str) -> str:
    match = re.search(_REASONING_END_MARKER, text)
    return text[match.end():].strip() if match else text


def _deterministic_requires_vision(raw_request: str) -> bool:
    lowered = raw_request.lower()
    return any(signal in lowered for signal in _VISION_SIGNALS)


def _parse_classification(raw_output: str) -> _Classification:
    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"Classifier returned no JSON object: {raw_output!r}")
    return _Classification(**json.loads(match.group(0)))


def _lmstudio_run(model_id: str, prompt: str) -> str:
    try:
        model = lms.llm(model_id)
        result = model.respond(prompt)
        raw = result.content if hasattr(result, "content") else str(result)
        return _strip_leaked_reasoning(raw)
    except Exception as e:
        raise InferenceError(f"Call to {model_id!r} failed: {e}") from e


# --- Public interface -----------------------------------------------------

class LLMGateway:
    """
    Single entry point: classify -> route -> run, hidden behind one call.

    `model_runner` defaults to the real LM Studio SDK call. Tests inject
    a fake here — that's the only seam this class exposes for testing.
    """

    def __init__(self, model_runner: Callable[[str, str], str] = None):
        self._model_runner = model_runner or _lmstudio_run

    def handle(self, raw_request: str, context_md: str = None) -> str:
        classification = self._classify(raw_request)

        if classification.skill_name != SkillType.UNKNOWN:
            print(f"Skill: {classification.skill_name.value.upper()}")
            print(f"\nRouting to {classification.skill_name.value.upper()} skill...")

            skill_result = run_skill(
                classification.skill_name,
                raw_request,
                context_md=context_md,
                model_id=_route(classification.task_type),
                model_runner=self._model_runner,
            )

            if skill_result.passed:
                print(f"✓ {classification.skill_name.value.upper()} skill checks passed")
            else:
                print(f"⚠️  {classification.skill_name.value.upper()} skill checks failed:")
                for item in skill_result.feedback:
                    print(f"  ✗ {item}")

            return skill_result.raw_response

        # Fallback: route by task_type (original behavior)
        model_id = _route(classification.task_type, context_tokens=len(raw_request) // 4)
        return self._model_runner(model_id, raw_request)


    def classify_only(self, raw_request: str) -> _Classification:
        """Exposed for inspection/debugging — not part of the main flow."""
        return self._classify(raw_request)

    def _classify(self, raw_request: str) -> _Classification:
        prompt = f"{_CLASSIFIER_SYSTEM_PROMPT}\n\nUser request: {raw_request}"
        raw_output = self._model_runner(_CLASSIFIER_MODEL_ID, prompt)
        classification = _parse_classification(raw_output)
        # Deterministic override — LLM's opinion on this field is discarded
        # unconditionally. See Benchmark 2: qwen3-1.7b inverted this field.
        classification.requires_vision = _deterministic_requires_vision(raw_request)
        return classification